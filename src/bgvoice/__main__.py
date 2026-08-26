"""Command-line interface for BGVoice."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from bgvoice.database import CharacterDatabase
from bgvoice.iecli import IeCli
from bgvoice.models import ExtractionProgress
from bgvoice.pipeline import extract_characters, extract_dialogues

_DEFAULT_DATABASE = Path("data/bgvoice.sqlite3")


def build_parser() -> argparse.ArgumentParser:
    """Describe the BGVoice command line."""
    parser = argparse.ArgumentParser(prog="bgvoice")
    commands = parser.add_subparsers(dest="command", required=True)

    characters = commands.add_parser(
        "extract-characters", help="inventory and extract all EET CRE resources"
    )
    dialogues = commands.add_parser(
        "extract-dialogues", help="inventory and extract all EET DLG resources"
    )
    for extraction in (characters, dialogues):
        extraction.add_argument(
            "--game", required=True, type=Path, help="game root containing chitin.key"
        )
        extraction.add_argument(
            "--database",
            type=Path,
            default=_DEFAULT_DATABASE,
            help=f"SQLite output path (default: {_DEFAULT_DATABASE})",
        )
        extraction.add_argument("--iecli", type=Path, help="override the bundled iecli executable")
        extraction.add_argument(
            "--workers",
            type=_positive_int,
            default=os.process_cpu_count() or 1,
            help="concurrent iecli processes (default: available logical CPU count)",
        )
        extraction.add_argument(
            "--refresh", action="store_true", help="re-extract records already completed"
        )
    characters.add_argument(
        "--inventory-only", action="store_true", help="skip per-CRE detail extraction"
    )

    attribution = commands.add_parser(
        "attribute-dialogues",
        help="account for every character reference and every extracted DLG",
    )
    attribution.add_argument(
        "--database", type=Path, default=_DEFAULT_DATABASE, help="SQLite database"
    )

    web = commands.add_parser("web", help="serve the read-only pipeline browser")
    web.add_argument("--database", type=Path, default=_DEFAULT_DATABASE, help="SQLite database")
    web.add_argument("--host", default="127.0.0.1", help="listen address")
    web.add_argument("--port", default=8000, type=_port, help="listen port")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a BGVoice command."""
    args = build_parser().parse_args(argv)

    if args.command == "web":
        import uvicorn

        from bgvoice.web import create_app

        uvicorn.run(create_app(args.database), host=args.host, port=args.port)
        return 0

    if args.command == "attribute-dialogues":
        with CharacterDatabase(args.database) as database:
            summary = database.rebuild_attributions()
            integrity = database.integrity_check()
        print(summary.model_dump_json(indent=2))
        print(f"SQLite integrity: {integrity}", file=sys.stderr)
        assert integrity == "ok", f"SQLite integrity check failed: {integrity}"
        return 0

    client = IeCli(args.iecli) if args.iecli is not None else IeCli()
    with CharacterDatabase(args.database) as database:
        if args.command == "extract-characters":
            summary = extract_characters(
                client,
                database,
                args.game,
                include_details=not args.inventory_only,
                workers=args.workers,
                refresh=args.refresh,
                progress=_print_character_progress,
            )
        else:
            summary = extract_dialogues(
                client,
                database,
                args.game,
                workers=args.workers,
                refresh=args.refresh,
                progress=_print_dialogue_progress,
            )
        integrity = database.integrity_check()
        character_count = database.stats().total

    print(summary.model_dump_json(indent=2))
    print(f"SQLite integrity: {integrity}", file=sys.stderr)
    print(f"Active character records: {character_count}", file=sys.stderr)
    assert integrity == "ok", f"SQLite integrity check failed: {integrity}"
    return 0 if summary.status == "complete" else 1


def _print_character_progress(progress: ExtractionProgress) -> None:
    print(
        f"CRE details {progress.completed}/{progress.total} "
        f"(ok={progress.succeeded}, failed={progress.failed})",
        file=sys.stderr,
        flush=True,
    )


def _print_dialogue_progress(progress: ExtractionProgress) -> None:
    print(
        f"DLG metrics {progress.completed}/{progress.total} "
        f"(ok={progress.succeeded}, failed={progress.failed})",
        file=sys.stderr,
        flush=True,
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _port(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return parsed


if __name__ == "__main__":  # pragma: no cover - interpreter entry point
    raise SystemExit(main())
