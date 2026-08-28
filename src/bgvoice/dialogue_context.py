"""Bulk-indexed predecessor context for dialogue direction."""

import asyncio
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from lancedb.pydantic import LanceModel
from pydantic import Field

from bgvoice.model_types import DialogueLineKind
from bgvoice.reader import PipelineReader
from bgvoice.storage_records import DialogueLineRecord

__all__ = ["DialogueHistoryIndex", "dialogue_history"]


@dataclass(frozen=True, slots=True)
class _DialogueNode:
    run_id: str
    resource_name: str
    state_index: int


@dataclass(frozen=True, slots=True)
class _DialogueContextTurn:
    node: _DialogueNode
    npc_text: str
    player_response: str | None


class _ContextLineRecord(LanceModel):
    id: str
    run_id: str
    dialogue_resource_name: str
    line_kind: DialogueLineKind = Field(strict=False)
    state_index: int
    transition_index: int | None
    text: str | None


class _ContextTransitionRecord(LanceModel):
    id: str
    run_id: str
    dialogue_resource_name: str
    state_index: int
    transition_index: int
    next_dialog: str | None
    next_state_index: int | None


@dataclass(frozen=True, slots=True)
class DialogueHistoryIndex:
    """Typed in-memory lookup for dialogue lines and incoming transitions."""

    _lines_by_node: Mapping[_DialogueNode, tuple[_ContextLineRecord, ...]]
    _internal_edges: Mapping[tuple[str, int], tuple[_ContextTransitionRecord, ...]]
    _named_edges: Mapping[tuple[str, int], tuple[_ContextTransitionRecord, ...]]

    @classmethod
    async def load(cls, reader: PipelineReader) -> DialogueHistoryIndex:
        """Bulk-load the narrow dialogue projections used by history resolution."""
        line_rows, edge_rows = await asyncio.gather(
            reader.lines_table.query()
            .select(list(_ContextLineRecord.model_fields))
            .to_pydantic(_ContextLineRecord),
            reader.transitions_table.query()
            .select(list(_ContextTransitionRecord.model_fields))
            .to_pydantic(_ContextTransitionRecord),
        )
        return cls._from_rows(
            cast(list[_ContextLineRecord], line_rows),
            cast(list[_ContextTransitionRecord], edge_rows),
        )

    @classmethod
    def _from_rows(
        cls,
        line_rows: Sequence[_ContextLineRecord],
        edge_rows: Sequence[_ContextTransitionRecord],
    ) -> DialogueHistoryIndex:
        lines: dict[_DialogueNode, list[_ContextLineRecord]] = defaultdict(list)
        for row in line_rows:
            lines[_DialogueNode(row.run_id, row.dialogue_resource_name, row.state_index)].append(
                row
            )

        internal: dict[tuple[str, int], list[_ContextTransitionRecord]] = defaultdict(list)
        named: dict[tuple[str, int], list[_ContextTransitionRecord]] = defaultdict(list)
        for edge in edge_rows:
            if edge.next_state_index is None:
                continue
            if edge.next_dialog is None:
                key = (edge.dialogue_resource_name.casefold(), edge.next_state_index)
                internal[key].append(edge)
            else:
                key = (edge.next_dialog.casefold(), edge.next_state_index)
                named[key].append(edge)

        return cls(
            _lines_by_node={
                node: tuple(sorted(rows, key=lambda row: row.id)) for node, rows in lines.items()
            },
            _internal_edges={key: tuple(rows) for key, rows in internal.items()},
            _named_edges={key: tuple(rows) for key, rows in named.items()},
        )


def dialogue_history(
    index: DialogueHistoryIndex,
    line: DialogueLineRecord,
) -> str | None:
    """Resolve and render up to two predecessor turns without exposing graph IDs."""
    target = _DialogueNode(line.run_id, line.dialogue_resource_name, line.state_index)
    visited = {(target.resource_name.casefold(), target.state_index)}
    nearest_first: list[_DialogueContextTurn] = []
    for _hop in range(2):
        turn = _previous_context(index, target, visited)
        if turn is None:
            break
        nearest_first.append(turn)
        target = turn.node
        visited.add((target.resource_name.casefold(), target.state_index))

    if not nearest_first:
        return None
    turns = list(reversed(nearest_first))
    rendered = _render_dialogue_history(turns)
    while len(rendered) > 1200 and len(turns) > 1:
        turns.pop(0)
        rendered = _render_dialogue_history(turns)
    return rendered if len(rendered) <= 1200 else rendered[:1199].rstrip() + "…"


def _previous_context(
    index: DialogueHistoryIndex,
    target: _DialogueNode,
    visited: set[tuple[str, int]],
) -> _DialogueContextTurn | None:
    target_name = target.resource_name.casefold()
    target_resref = target_name.removesuffix(".dlg")
    incoming = sorted(
        (
            *index._internal_edges.get((target_name, target.state_index), ()),
            *index._named_edges.get((target_resref, target.state_index), ()),
        ),
        key=lambda edge: (
            edge.dialogue_resource_name.casefold() != target_name,
            edge.dialogue_resource_name.casefold(),
            edge.state_index,
            edge.transition_index,
            edge.id,
        ),
    )
    for edge in incoming:
        node = _DialogueNode(edge.run_id, edge.dialogue_resource_name, edge.state_index)
        if (node.resource_name.casefold(), node.state_index) not in visited:
            turn = _context_turn(index, node, edge.transition_index)
            if turn is not None:
                return turn

    if target.state_index == 0:
        return None
    fallback = _DialogueNode(target.run_id, target.resource_name, target.state_index - 1)
    if (fallback.resource_name.casefold(), fallback.state_index) in visited:
        return None
    return _context_turn(index, fallback, None)


def _context_turn(
    index: DialogueHistoryIndex,
    node: _DialogueNode,
    transition_index: int | None,
) -> _DialogueContextTurn | None:
    rows = index._lines_by_node.get(node, ())
    npc_text = next(
        (
            " ".join(row.text.split())
            for row in rows
            if row.line_kind is DialogueLineKind.NPC and row.text
        ),
        None,
    )
    if npc_text is None:
        return None
    player_response = next(
        (
            " ".join(row.text.split())
            for row in rows
            if row.line_kind is DialogueLineKind.PLAYER
            and row.transition_index == transition_index
            and row.text
        ),
        None,
    )
    return _DialogueContextTurn(node, npc_text, player_response)


def _render_dialogue_history(turns: Sequence[_DialogueContextTurn]) -> str:
    lines = ["Unspoken scene context:"]
    for index, turn in enumerate(turns, start=1):
        if len(turns) > 1:
            proximity = "immediate" if index == len(turns) else "earlier"
            lines.append(f"Context turn {index} ({proximity}):")
        lines.append(f"Previous NPC/scene line: {turn.npc_text}")
        lines.append(
            "Player response: " + (turn.player_response or "none (automatic scene transition)")
        )
    return "\n".join(lines)
