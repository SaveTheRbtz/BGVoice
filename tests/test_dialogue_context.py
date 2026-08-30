"""Deterministic dialogue-history traversal."""

import bgvoice.dialogue_context as context_module
from bgvoice.dialogue_context import DialogueHistoryIndex, dialogue_history
from bgvoice.model_types import DialogueLineKind
from tests.factories import make_dialogue_line


def _context_line(
    dialogue: str,
    state: int,
    text: str,
    *,
    kind: DialogueLineKind = DialogueLineKind.NPC,
    transition: int | None = None,
) -> context_module._ContextLineRecord:
    suffix = "-" if transition is None else str(transition)
    return context_module._ContextLineRecord(
        id=f"{dialogue}:{kind.value}:{state}:{suffix}",
        run_id="run",
        dialogue_resource_name=dialogue,
        line_kind=kind,
        state_index=state,
        transition_index=transition,
        text=text,
    )


def _edge(
    dialogue: str,
    state: int,
    transition: int,
    next_dialogue: str | None,
    next_state: int,
) -> context_module._ContextTransitionRecord:
    return context_module._ContextTransitionRecord(
        id=f"{dialogue}:{state}:{transition}",
        run_id="run",
        dialogue_resource_name=dialogue,
        state_index=state,
        transition_index=transition,
        next_dialog=next_dialogue,
        next_state_index=next_state,
    )


def test_dialogue_history_index_preserves_two_hop_edge_selection_and_fallback() -> None:
    line_rows = [
        _context_line("A.DLG", 1, "  Earlier   NPC  "),
        _context_line(
            "A.DLG",
            1,
            " First   choice ",
            kind=DialogueLineKind.PLAYER,
            transition=7,
        ),
        _context_line("B.DLG", 0, "Immediate NPC"),
        _context_line(
            "B.DLG",
            0,
            "Second choice",
            kind=DialogueLineKind.PLAYER,
            transition=3,
        ),
        _context_line("B.DLG", 4, "Lower-priority internal edge"),
        _context_line("F.DLG", 1, "Fallback context"),
    ]
    edge_rows = [
        _edge("B.DLG", 4, 1, None, 2),
        _edge("B.DLG", 0, 3, "b", 2),
        _edge("A.DLG", 1, 7, "B", 0),
    ]
    index = DialogueHistoryIndex._from_rows(line_rows, edge_rows)

    assert dialogue_history(index, make_dialogue_line("B.DLG", 2)) == (
        "Unspoken scene context:\n"
        "Context turn 1 (earlier):\n"
        "Previous NPC/scene line: Earlier NPC\n"
        "Player response: First choice\n"
        "Context turn 2 (immediate):\n"
        "Previous NPC/scene line: Immediate NPC\n"
        "Player response: Second choice"
    )
    assert dialogue_history(index, make_dialogue_line("F.DLG", 2)) == (
        "Unspoken scene context:\n"
        "Previous NPC/scene line: Fallback context\n"
        "Player response: none (automatic scene transition)"
    )
