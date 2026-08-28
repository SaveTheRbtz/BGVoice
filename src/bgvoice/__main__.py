"""Command-line interface for BGVoice."""

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from bgvoice.database import PipelineDatabase
from bgvoice.direction_audit import (
    DEFAULT_SIMILARITY_THRESHOLD,
    audit_directions,
)
from bgvoice.generation import generate
from bgvoice.iecli import IeCli
from bgvoice.mod_export import export_mod
from bgvoice.model_types import RunStatus
from bgvoice.pipeline import (
    extract_characters,
    extract_dialogues,
    extract_metadata,
    extract_portraits,
)
from bgvoice.pipeline_models import ExtractionProgress

_DEFAULT_DATABASE = Path("data/bgvoice.lancedb")
_DEFAULT_DIRECTION_AUDIT = Path("data/direction-mismatches.json")
_DEFAULT_MOD_OUTPUT = Path("data/bgvoice-eet-mod")


def build_parser() -> argparse.ArgumentParser:
    """Describe the BGVoice command line."""
    workers = os.process_cpu_count()
    assert workers is not None, "Python could not determine the available CPU count"
    parser = argparse.ArgumentParser(prog="bgvoice")
    commands = parser.add_subparsers(dest="command", required=True)

    metadata = commands.add_parser(
        "extract-metadata",
        help="import effective engine, campaign, dialogue-link, and voice metadata",
    )
    characters = commands.add_parser(
        "extract-characters", help="inventory and extract all EET CRE resources"
    )
    dialogues = commands.add_parser(
        "extract-dialogues", help="inventory and extract all EET DLG resources"
    )
    portraits = commands.add_parser(
        "extract-portraits", help="store CRE portrait resources as deduplicated PNG images"
    )
    for extraction in (metadata, characters, portraits, dialogues):
        extraction.add_argument(
            "--game", required=True, type=Path, help="game root containing chitin.key"
        )
        extraction.add_argument(
            "--database",
            type=Path,
            default=_DEFAULT_DATABASE,
            help=f"LanceDB directory (default: {_DEFAULT_DATABASE})",
        )
        extraction.add_argument("--iecli", type=Path, help="override the bundled iecli executable")
        extraction.add_argument(
            "--workers",
            type=_positive_int,
            default=workers,
            help="concurrent iecli processes (default: available logical CPU count)",
        )
    for extraction in (characters, dialogues):
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
        "--database", type=Path, default=_DEFAULT_DATABASE, help="LanceDB directory"
    )

    generation = commands.add_parser(
        "generate",
        help="design voices, direct dialogue, and generate missing audio",
    )
    generation.add_argument(
        "--voice",
        action="append",
        required=True,
        help="canonical voice ID or display name; repeat for multiple voices",
    )
    generation.add_argument(
        "--lines-per-voice",
        type=_line_limit,
        default=100,
        help="maximum round-robin lines per voice, or 'all' (default: 100)",
    )
    generation.add_argument(
        "--database", type=Path, default=_DEFAULT_DATABASE, help="LanceDB directory"
    )
    generation.add_argument(
        "--recreate-voices",
        action="store_true",
        help="delete and recreate every selected character voice, direction, and audio",
    )

    audit = commands.add_parser(
        "audit-directions",
        help="find directed dialogue that no longer matches its extracted source text",
    )
    audit.add_argument("--database", type=Path, default=_DEFAULT_DATABASE, help="LanceDB directory")
    audit.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_DIRECTION_AUDIT,
        help=f"JSON mismatch report (default: {_DEFAULT_DIRECTION_AUDIT})",
    )
    audit.add_argument(
        "--similarity-threshold",
        type=_percentage,
        default=DEFAULT_SIMILARITY_THRESHOLD,
        help="send pairs below this RapidFuzz score to Luna (default: 25)",
    )

    export = commands.add_parser(
        "export-mod",
        help="build a WeiDU EET mod containing both generated-audio policies",
    )
    export.add_argument(
        "--database", type=Path, default=_DEFAULT_DATABASE, help="LanceDB directory"
    )
    export.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_MOD_OUTPUT,
        help=f"replaceable mod directory (default: {_DEFAULT_MOD_OUTPUT})",
    )

    web = commands.add_parser("web", help="serve the read-only pipeline browser")
    web.add_argument("--database", type=Path, default=_DEFAULT_DATABASE, help="LanceDB directory")
    web.add_argument("--host", default="127.0.0.1", help="listen address")
    web.add_argument("--port", default=8000, type=_port, help="listen port")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a BGVoice command."""
    load_dotenv()
    args = build_parser().parse_args(argv)
    if args.command == "web":
        import uvicorn

        from bgvoice.web import create_app

        uvicorn.run(create_app(args.database), host=args.host, port=args.port)
        return 0
    if args.command == "attribute-dialogues":
        assert args.database.expanduser().resolve().is_dir(), (
            f"pipeline database does not exist: {args.database}"
        )
        summary = PipelineDatabase(args.database).rebuild_attributions()
        print(summary.model_dump_json(indent=2))
        return 0
    if args.command == "generate":
        logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")
        logging.getLogger("bgvoice.generation_ai").setLevel(logging.INFO)
        summary = asyncio.run(
            generate(
                args.database,
                args.voice,
                args.lines_per_voice,
                os.environ["OPENAI_API_KEY"],
                os.environ["INWORLD_API_KEY"],
                recreate_voices=args.recreate_voices,
            )
        )
        print(summary.model_dump_json(indent=2))
        return 0
    if args.command == "audit-directions":
        logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")
        logging.getLogger("bgvoice.generation_ai").setLevel(logging.INFO)
        summary = asyncio.run(
            audit_directions(
                args.database,
                args.output,
                os.environ["OPENAI_API_KEY"],
                similarity_threshold=args.similarity_threshold,
            )
        )
        print(summary.model_dump_json(indent=2))
        return 0
    if args.command == "export-mod":
        summary = asyncio.run(export_mod(args.database, args.output))
        print(summary.model_dump_json(indent=2))
        return 0
    return _extract(args)


def _extract(args: argparse.Namespace) -> int:
    client = IeCli(args.iecli) if args.iecli is not None else IeCli()
    database = PipelineDatabase(args.database)
    if args.command == "extract-metadata":
        summary = extract_metadata(client, database, args.game, workers=args.workers)
    elif args.command == "extract-characters":
        summary = extract_characters(
            client,
            database,
            args.game,
            include_details=not args.inventory_only,
            workers=args.workers,
            refresh=args.refresh,
            progress=_print_character_progress,
        )
    elif args.command == "extract-portraits":
        summary = extract_portraits(client, database, args.game, workers=args.workers)
    else:
        summary = extract_dialogues(
            client,
            database,
            args.game,
            workers=args.workers,
            refresh=args.refresh,
            progress=_print_dialogue_progress,
        )
    print(summary.model_dump_json(indent=2))
    if args.command != "extract-metadata":
        print(f"Active character records: {database.stats().total}", file=sys.stderr)
    return 0 if summary.status is RunStatus.COMPLETE else 1


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


def _line_limit(value: str) -> int | None:
    return None if value.casefold() == "all" else _positive_int(value)


def _port(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return parsed


def _percentage(value: str) -> float:
    parsed = float(value)
    if not 0 <= parsed <= 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return parsed


if __name__ == "__main__":  # pragma: no cover - interpreter entry point
    raise SystemExit(main())
