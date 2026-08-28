"""Typed bulk loading and deterministic dialogue-history traversal."""

from pathlib import Path
from typing import cast

import pytest

import bgvoice.dialogue_context as context_module
from bgvoice.dialogue_context import DialogueHistoryIndex, dialogue_history
from bgvoice.model_types import DialogueLineKind
from bgvoice.reader import PipelineReader
from bgvoice.storage_records import DialogueLineRecord


def _line(dialogue: str, state: int) -> DialogueLineRecord:
    return DialogueLineRecord(
        id=f"{dialogue}:npc:{state}:-",
        run_id="run",
        dialogue_resource_name=dialogue,
        line_kind=DialogueLineKind.NPC,
        state_index=state,
        strref=state,
        text=f"Line {state}",
        tokens=[],
        serialized_size=10,
        search_text=f"Line {state}",
    )


def test_dialogue_history_index_preserves_two_hop_edge_selection_and_fallback() -> None:
    line_rows = [
        context_module._ContextLineRecord(
            id="A.DLG:npc:1:-",
            run_id="run",
            dialogue_resource_name="A.DLG",
            line_kind=DialogueLineKind.NPC,
            state_index=1,
            transition_index=None,
            text="  Earlier   NPC  ",
        ),
        context_module._ContextLineRecord(
            id="A.DLG:player:1:7",
            run_id="run",
            dialogue_resource_name="A.DLG",
            line_kind=DialogueLineKind.PLAYER,
            state_index=1,
            transition_index=7,
            text=" First   choice ",
        ),
        context_module._ContextLineRecord(
            id="B.DLG:npc:0:-",
            run_id="run",
            dialogue_resource_name="B.DLG",
            line_kind=DialogueLineKind.NPC,
            state_index=0,
            transition_index=None,
            text="Immediate NPC",
        ),
        context_module._ContextLineRecord(
            id="B.DLG:player:0:3",
            run_id="run",
            dialogue_resource_name="B.DLG",
            line_kind=DialogueLineKind.PLAYER,
            state_index=0,
            transition_index=3,
            text="Second choice",
        ),
        context_module._ContextLineRecord(
            id="B.DLG:npc:4:-",
            run_id="run",
            dialogue_resource_name="B.DLG",
            line_kind=DialogueLineKind.NPC,
            state_index=4,
            transition_index=None,
            text="Lower-priority internal edge",
        ),
        context_module._ContextLineRecord(
            id="F.DLG:npc:1:-",
            run_id="run",
            dialogue_resource_name="F.DLG",
            line_kind=DialogueLineKind.NPC,
            state_index=1,
            transition_index=None,
            text="Fallback context",
        ),
    ]
    edge_rows = [
        context_module._ContextTransitionRecord(
            id="B.DLG:4:1",
            run_id="run",
            dialogue_resource_name="B.DLG",
            state_index=4,
            transition_index=1,
            next_dialog=None,
            next_state_index=2,
        ),
        context_module._ContextTransitionRecord(
            id="B.DLG:0:3",
            run_id="run",
            dialogue_resource_name="B.DLG",
            state_index=0,
            transition_index=3,
            next_dialog="b",
            next_state_index=2,
        ),
        context_module._ContextTransitionRecord(
            id="A.DLG:1:7",
            run_id="run",
            dialogue_resource_name="A.DLG",
            state_index=1,
            transition_index=7,
            next_dialog="B",
            next_state_index=0,
        ),
    ]
    index = DialogueHistoryIndex._from_rows(line_rows, edge_rows)

    assert dialogue_history(index, _line("B.DLG", 2)) == (
        "Unspoken scene context:\n"
        "Context turn 1 (earlier):\n"
        "Previous NPC/scene line: Earlier NPC\n"
        "Player response: First choice\n"
        "Context turn 2 (immediate):\n"
        "Previous NPC/scene line: Immediate NPC\n"
        "Player response: Second choice"
    )
    assert dialogue_history(index, _line("F.DLG", 2)) == (
        "Unspoken scene context:\n"
        "Previous NPC/scene line: Fallback context\n"
        "Player response: none (automatic scene transition)"
    )


@pytest.mark.anyio
async def test_dialogue_history_index_bulk_loads_typed_scenario_rows(
    shared_scenario_database: Path,
) -> None:
    reader = await PipelineReader.open(shared_scenario_database)
    try:
        rows = cast(
            list[DialogueLineRecord],
            await reader.lines_table.query().to_pydantic(DialogueLineRecord),
        )
        index = await DialogueHistoryIndex.load(reader)
    finally:
        reader.close()

    target = next(
        row
        for row in rows
        if row.dialogue_resource_name == "AERIE.DLG"
        and row.line_kind is DialogueLineKind.NPC
        and row.state_index == 1
    )
    history = dialogue_history(index, target)
    assert history is not None
    assert "Previous NPC/scene line: Hello." in history
    assert "Player response: Hi." in history
