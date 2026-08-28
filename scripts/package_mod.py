"""Export, validate, and archive one versioned BGVoice WeiDU release."""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypedDict

from bgvoice.mod_export import create_archive, export_mod


class PackageSummary(TypedDict):
    version: str
    output: str
    archive: str
    source_game: str
    generated_lines: int
    audio_files: int
    dialogue_files: int
    audio_bytes: int
    weidu_files_parsed: int
    archive_files: int
    archive_bytes: int
    archive_crc_verified: bool
    sha256: str


def parse_mod(output: Path) -> int:
    """Parse every generated WeiDU source without loading or modifying a game."""
    executable = output / "setup-bgvoice.exe"
    files = [
        ("TP2", output / "setup-bgvoice.tp2"),
        ("TPA", output / "bgvoice" / "lib" / "install.tpa"),
        *(("TPA", path) for path in sorted((output / "bgvoice" / "dialogue").glob("*.tpa"))),
    ]
    workers = os.process_cpu_count()
    assert workers is not None, "Python could not determine the available CPU count"

    def parse(source: tuple[str, Path]) -> None:
        kind, path = source
        subprocess.run(
            [
                executable,
                "--noautoupdate",
                "--no-auto-tp2",
                "--nogame",
                "--no-exit-pause",
                "--log",
                os.devnull,
                "--parse-check",
                kind,
                path,
            ],
            cwd=output,
            stdout=subprocess.DEVNULL,
            check=True,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in pool.map(parse, files):
            pass
    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new BGVoice export directory")
    parser.add_argument("archive", type=Path, help="new release ZIP; must not already exist")
    parser.add_argument("--version", default="1.0.0", help="mod version (default: 1.0.0)")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/bgvoice.lancedb"),
        help="LanceDB directory (default: data/bgvoice.lancedb)",
    )
    args = parser.parse_args()
    output = args.output.expanduser().absolute()
    archive = args.archive.expanduser().absolute()
    assert not output.exists(), f"export already exists: {output}"
    assert not archive.exists(), f"archive already exists: {archive}"

    exported = asyncio.run(export_mod(args.database, output, version=args.version))
    parsed = parse_mod(output)
    archived = create_archive(output, archive)
    with archive.open("rb") as stream:
        sha256 = hashlib.file_digest(stream, "sha256").hexdigest()

    summary: PackageSummary = {
        "version": args.version,
        "output": exported.output,
        "archive": str(archive),
        "source_game": exported.source_game,
        "generated_lines": exported.generated_lines,
        "audio_files": exported.audio_files,
        "dialogue_files": exported.dialogue_files,
        "audio_bytes": exported.audio_bytes,
        "weidu_files_parsed": parsed,
        "archive_files": archived,
        "archive_bytes": archive.stat().st_size,
        "archive_crc_verified": True,
        "sha256": sha256,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
