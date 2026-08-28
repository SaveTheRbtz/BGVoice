"""Semantic direction-audit behavior."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from openai import AsyncOpenAI

import bgvoice.direction_audit as audit_module
from bgvoice.direction_audit import (
    DirectionAuditReport,
    MismatchBatchResult,
    audit_directions,
    build_mismatch_prompt,
    suspicious_pairs,
)
from bgvoice.generation_store import GenerationStore
from bgvoice.storage_records import CharacterDirection, DirectedLineRecord


def _direction(voice_id: str, line_id: str, text: str) -> DirectedLineRecord:
    return DirectedLineRecord(
        id=DirectedLineRecord.id_for(voice_id, line_id),
        voice_id=voice_id,
        dialogue_line_id=line_id,
        character=CharacterDirection(directed_dialogue=text),
        created_at="2026-08-28T12:00:00+00:00",
    )


def test_rapidfuzz_prefilter_removes_templates_and_tts_hints() -> None:
    faithful = _direction("imoen", "IMOEN.DLG:npc:0:-", "[urgently] We must leave now!")
    unrelated = _direction("imoen", "IMOEN.DLG:npc:1:-", "[warmly] Zebras.")
    sources = {
        faithful.dialogue_line_id: "<CHARNAME>, we must leave now!",
        unrelated.dialogue_line_id: "The portal will collapse unless we leave.",
    }

    candidates = suspicious_pairs([faithful, unrelated], sources, 25)

    assert [pair.id for pair in candidates] == [unrelated.id]
    assert candidates[0].comparison_original == "the portal will collapse unless we leave."
    assert candidates[0].comparison_directed == "zebras."


def test_luna_prompt_defines_the_semantic_boundary_and_escapes_dialogue() -> None:
    direction = _direction("imoen", "IMOEN.DLG:npc:0:-", "Bread & water.")
    pair = suspicious_pairs(
        [direction],
        {direction.dialogue_line_id: "No fish <CHARNAME> & no wine."},
        100,
    )[0]

    prompt = build_mismatch_prompt([pair])

    assert f'<pair id="{direction.id}">' in prompt
    assert "No fish &lt;CHARNAME&gt; &amp; no wine." in prompt
    assert "Bread &amp; water." in prompt
    assert "A low fuzzy-match score is not evidence" in prompt
    assert "text copied from a neighboring line" in prompt
    assert "reversed polarity" in prompt
    assert "removal or natural neutral rewriting" in prompt
    assert "*sighs* -> [sigh] is faithful" in prompt
    assert "... -> [sigh] may be faithful" in prompt
    assert "no matter how long or detailed the omitted prose is" in " ".join(prompt.split())
    assert "Indeed. *He turns away" in prompt
    assert '"Get inside!" He pulls the door shut' in prompt
    assert "She sighs when it is clear" in prompt
    assert "narrated event disappeared" in prompt
    assert "� is always a mismatch" in prompt
    assert "complete parenthetical or asterisk-wrapped narrative sentence" in prompt
    assert "Evaluate every requested pair from start to finish" in prompt
    assert "each pair is independent" in prompt.casefold()


class _Responses:
    def __init__(self, mismatched_id: str | None) -> None:
        self.mismatched_id = mismatched_id
        self.calls: list[dict[str, object]] = []

    async def parse(self, **arguments: object) -> object:
        self.calls.append(arguments)
        return SimpleNamespace(
            id="response-audit",
            usage=None,
            output_parsed=MismatchBatchResult(
                mismatched_ids=[] if self.mismatched_id is None else [self.mismatched_id]
            ),
        )


class _Client:
    def __init__(self, mismatched_id: str | None) -> None:
        self.responses = _Responses(mismatched_id)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_audit_writes_typed_json_without_modifying_directions(
    scenario_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    faithful = _direction("aerie", "AERIE.DLG:npc:0:-", "[warmly] Hello.")
    mismatch = _direction("aerie", "AERIE.DLG:npc:1:-", "[cheerfully] Xyzygy �.")
    store = await GenerationStore.open(scenario_database)
    try:
        await store.upsert_directed_lines([faithful, mismatch])
    finally:
        store.close()

    client = _Client(None)
    monkeypatch.setattr(audit_module, "AsyncOpenAI", lambda **_: client)
    output = tmp_path / "reports" / "mismatches.json"

    summary = await audit_directions(scenario_database, output, "test-key")
    report = DirectionAuditReport.model_validate_json(output.read_text(encoding="utf-8"))

    assert summary.model_dump() == {
        "directed_lines": 2,
        "rapidfuzz_candidates": 1,
        "model_batches": 1,
        "mismatches": 1,
        "output": str(output.resolve()),
    }
    assert report.directed_lines == 2
    assert report.rapidfuzz_candidates == 1
    assert [item.model_dump() for item in report.mismatches] == [
        {
            "id": mismatch.id,
            "voice_id": "aerie",
            "dialogue_line_id": "AERIE.DLG:npc:1:-",
            "similarity": report.mismatches[0].similarity,
            "original": "A quest for <DAYANDMONTH>.",
            "directed": "[cheerfully] Xyzygy �.",
        }
    ]
    assert json.loads(output.read_text(encoding="utf-8"))["mismatches"][0]["id"] == mismatch.id
    assert client.closed
    assert len(client.responses.calls) == 1
    call = client.responses.calls[0]
    assert call["model"] == "gpt-5.6-luna"
    assert call["reasoning"] == {"effort": "medium"}
    assert call["tools"] == []
    assert call["tool_choice"] == "none"
    assert "max_output_tokens" not in call
    assert call["text_format"] is MismatchBatchResult

    stored = await GenerationStore.open(scenario_database)
    try:
        directions = await stored.directed_lines(["aerie"])
        assert sorted(directions, key=lambda row: row.id) == sorted(
            [faithful, mismatch], key=lambda row: row.id
        )
    finally:
        stored.close()


@pytest.mark.anyio
async def test_model_ignores_unrequested_pair_ids(caplog: pytest.LogCaptureFixture) -> None:
    direction = _direction("imoen", "IMOEN.DLG:npc:0:-", "Unrelated text.")
    pair = suspicious_pairs(
        [direction],
        {direction.dialogue_line_id: "The original line is completely different."},
        100,
    )[0]
    client = _Client("invented-id")

    mismatches, batch_count = await audit_module.find_mismatches(cast(AsyncOpenAI, client), [pair])

    assert mismatches == set()
    assert batch_count == 1
    assert "returned unknown mismatch IDs" in caplog.text


@pytest.mark.anyio
async def test_luna_batches_prioritize_review_quality() -> None:
    direction = _direction("imoen", "IMOEN.DLG:npc:0:-", "Unrelated text.")
    pair = suspicious_pairs(
        [direction],
        {direction.dialogue_line_id: "The original line is completely different."},
        100,
    )[0]
    pairs = [replace(pair, id=f"d-{index:032x}") for index in range(26)]
    client = _Client(None)

    mismatches, batch_count = await audit_module.find_mismatches(cast(AsyncOpenAI, client), pairs)

    assert mismatches == set()
    assert batch_count == 2
    assert [call["reasoning"] for call in client.responses.calls] == [
        {"effort": "medium"},
        {"effort": "medium"},
    ]
