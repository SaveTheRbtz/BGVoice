"""The cost-sensitive command-line generation contract."""

from collections.abc import Sequence
from pathlib import Path

import pytest

import bgvoice.__main__ as cli
from bgvoice.generation import GenerationSummary


def test_generation_options_reach_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[Path, Sequence[str] | None, int | None, bool, int]] = []

    async def generate(
        database: Path,
        voices: Sequence[str] | None,
        lines_per_voice: int | None,
        _openai_key: str,
        _inworld_key: str,
        *,
        recreate_voices: bool,
        generic_max_lines: int,
    ) -> GenerationSummary:
        calls.append((database, voices, lines_per_voice, recreate_voices, generic_max_lines))
        return GenerationSummary(
            voices=len(voices or ()),
            selected_lines=0,
            directed_lines=0,
            generated_audio=0,
            voice_creation_failures=0,
            dialogue_direction_failures=0,
            audio_generation_failures=0,
        )

    monkeypatch.setattr(cli, "generate", generate)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("INWORLD_API_KEY", "test-inworld-key")
    database = tmp_path / "pipeline.lancedb"

    assert (
        cli.main(
            [
                "generate",
                "--database",
                str(database),
                "--voice",
                "Imoen",
                "--voice",
                "Gorion",
                "--lines-per-voice",
                "all",
                "--recreate-voices",
                "--generic-max-lines",
                "0",
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "generate",
                "--database",
                str(database),
                "--all-sparse",
                "--lines-per-voice",
                "3",
                "--generic-max-lines",
                "7",
            ]
        )
        == 0
    )
    assert calls == [
        (database, ["Imoen", "Gorion"], None, True, 0),
        (database, None, 3, False, 7),
    ]
