"""Find directed dialogue that no longer matches its extracted source text."""

import asyncio
import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, cast

from lancedb.pydantic import LanceModel
from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam
from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz

from bgvoice.generation_ai import log_openai_usage
from bgvoice.model_types import utc_now
from bgvoice.reader import PipelineReader
from bgvoice.storage_records import DirectedLineRecord

AUDIT_MODEL = "gpt-5.6-luna"
AUDIT_BATCH_SIZE = 25
AUDIT_CONCURRENCY = 100
DEFAULT_SIMILARITY_THRESHOLD = 80.0

_TEMPLATE = re.compile(r"<[^<>\r\n]+>")
_TTS_HINT = re.compile(r"\[[^\]\r\n]+]")

_AUDIT_INSTRUCTIONS = """Judge whether each directed line preserves the substantive spoken meaning
of its original Baldur's Gate dialogue line. Each pair is independent. Compare only the
<original> and <directed> text inside that pair; never borrow text or meaning from another pair.

The pairs were selected only because their lexical similarity is unusually low after removing
Infinity Engine template tokens and TTS instruction hints. A low fuzzy-match score is not evidence
of a semantic mismatch by itself.

Do not flag a pair for any of these allowed transformations:
- removal or natural neutral rewriting of an Infinity Engine template such as a player name,
  pronoun, race, title, or party-slot token;
- removal of source-only asterisks or enclosing punctuation, and removal or conversion of an
  embedded stage direction when the spoken meaning remains;
- conversion of a source that consists only of an audible action such as *sighs*, *laughs*,
  *coughs*, or *yawns* into the equivalent TTS nonverbal hint such as [sigh] or [laugh];
- omission of parenthetical or asterisk-delimited descriptive/stage prose when the original also
  contains actual speech and the directed result preserves that speech; this remains acceptable no
  matter how long or detailed the omitted prose is;
- omission of third-person scene narration surrounding preserved spoken words, including actions
  and events before or after the speech; judge whether the speech itself was preserved, not whether
  every narrated event would be audible;
- conversion of a sentence describing an audible nonverbal into that nonverbal's TTS hint, even
  when the source also explains its cause or includes visual modifiers;
- punctuation, capitalization, contractions, word order, synonyms, neutral pronouns, or a concise
  paraphrase that retains the same meaning;
- removing a vocative, filler word, hesitation, or other nonessential flourish.
- conversion of a source containing only an ellipsis or other punctuation-only silent beat into a
  brief pause, breath, sigh, or hesitation hint.
- replacement of decorative punctuation or asterisks that carry no substantive meaning with a
  brief nonverbal beat.

Flag a pair when the directed line clearly cannot be a faithful spoken rendition of the original.
Examples include text copied from a neighboring line, an unrelated replacement, reversed polarity
or intent, changed actor/object/number, invented substantive facts, or omission of an essential
question, command, condition, or clause. Also flag substantive scene narration that has been
collapsed into only a delivery hint. A directed line containing the Unicode replacement character
� is always a mismatch because it is corrupted, even when its remaining words match. A directed
line consisting only of an emoji, emoticon, or unpronounceable punctuation is also a mismatch when
the original contains a meaningful action or statement. If the difference is merely stylistic or
the two readings are plausibly equivalent, do not flag it. Do not flag a pair merely because one
version is longer.

When the original is a complete parenthetical or asterisk-wrapped narrative sentence and the
directed result contains only square-bracket hints with no spoken words, flag it unless the original
itself consists only of an audible nonverbal such as a sigh, laugh, cough, yawn, snort, or gulp.

Boundary examples:
- *sighs* -> [sigh] is faithful: both represent the same audible nonverbal.
- *whispering* We must go. -> [speak quietly] We must go. is faithful.
- Indeed. *He turns away and silently crosses the room.* -> Indeed. is faithful because the spoken
  text is preserved and the omitted material is stage prose.
- <CHARNAME>... -> [hesitate] may be faithful because the runtime-only vocative was removed and no
  substantive statement remains.
- ... -> [sigh] may be faithful because both represent a nonverbal conversational beat.
- (He laughs, smiling apologetically.) -> [laugh] may be faithful because the core audible action is
  preserved and the remaining modifiers are visual.
- "Get inside!" He pulls the door shut behind you. -> [shout urgently] Get inside! is faithful
  because all spoken words remain and the omitted sentence is scene narration.
- (She sighs when it is clear you will not listen.) -> [sigh] is faithful because the audible action
  is preserved; the explanatory clause need not be spoken.
- (Imoen slowly nods, relieved of a heavy burden.) -> [sound relieved] is a mismatch because the
  narrated event disappeared and the hint is not spoken narration.
- I did not betray you. -> I betrayed you. is a mismatch because the polarity reversed.

Return only the supplied Structured Output. Copy the exact IDs of confirmed mismatches into
mismatched_ids. Evaluate every requested pair from start to finish; do not stop after finding a few
strong examples, and do not omit a clear mismatch because another pair is more extreme. Do not
return IDs for acceptable pairs and do not invent IDs."""


class _Model(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class MismatchBatchResult(_Model):
    """Semantic mismatches confirmed within one requested batch."""

    mismatched_ids: Annotated[
        list[str],
        Field(
            description=(
                "Exact pair IDs whose directed text clearly changes, replaces, contradicts, or "
                "materially omits the original spoken meaning, including corrupted replacement "
                "characters. Empty when every pair is faithful."
            )
        ),
    ]


class DirectionMismatch(_Model):
    """One confirmed mismatch with enough source data for follow-up processing."""

    id: str
    voice_id: str
    dialogue_line_id: str
    similarity: float = Field(ge=0, le=100)
    original: str
    directed: str


class DirectionAuditSummary(_Model):
    """Compact audit totals printed by the command line."""

    directed_lines: int = Field(ge=0)
    rapidfuzz_candidates: int = Field(ge=0)
    model_batches: int = Field(ge=0)
    mismatches: int = Field(ge=0)
    output: str


class DirectionAuditReport(_Model):
    """Complete deterministic audit artifact."""

    created_at: str
    model: str
    similarity_threshold: float = Field(ge=0, le=100)
    directed_lines: int = Field(ge=0)
    rapidfuzz_candidates: int = Field(ge=0)
    model_batches: int = Field(ge=0)
    mismatches: list[DirectionMismatch]


class _DialogueText(LanceModel):
    id: str
    text: str | None


@dataclass(frozen=True, slots=True)
class _AuditPair:
    id: str
    voice_id: str
    dialogue_line_id: str
    original: str
    directed: str
    comparison_original: str
    comparison_directed: str
    similarity: float


def comparison_text(text: str, pattern: re.Pattern[str]) -> str:
    """Remove non-spoken markup and normalize text for lexical comparison."""
    return " ".join(pattern.sub("", text).casefold().split())


def suspicious_pairs(
    directions: list[DirectedLineRecord],
    source_texts: dict[str, str],
    threshold: float,
) -> list[_AuditPair]:
    """Apply the inexpensive lexical prefilter to every stored direction."""
    pairs: list[_AuditPair] = []
    for direction in directions:
        original = source_texts[direction.dialogue_line_id]
        if direction.character is not None:
            directed = direction.character.directed_dialogue
        else:
            assert direction.narrator is not None
            directed = direction.narrator.directed_dialogue
        comparison_original = comparison_text(original, _TEMPLATE)
        comparison_directed = comparison_text(directed, _TTS_HINT)
        similarity = fuzz.ratio(comparison_original, comparison_directed)
        if similarity < threshold or "�" in directed:
            pairs.append(
                _AuditPair(
                    direction.id,
                    direction.voice_id,
                    direction.dialogue_line_id,
                    original,
                    directed,
                    comparison_original,
                    comparison_directed,
                    similarity,
                )
            )
    return sorted(pairs, key=lambda pair: pair.id)


def build_mismatch_prompt(pairs: list[_AuditPair]) -> str:
    """Render one escaped, ID-addressable semantic-audit request."""
    requested = "\n\n".join(
        f'<pair id="{pair.id}">\n'
        f"<original>{html.escape(pair.original)}</original>\n"
        f"<directed>{html.escape(pair.directed)}</directed>\n"
        "</pair>"
        for pair in pairs
    )
    return f"{_AUDIT_INSTRUCTIONS}\n\nRequested pairs:\n{requested}"


async def find_mismatches(
    client: AsyncOpenAI,
    pairs: list[_AuditPair],
    *,
    model: str = AUDIT_MODEL,
) -> tuple[set[str], int]:
    """Ask Luna to adjudicate all RapidFuzz candidates in bounded batches."""
    batches = [
        pairs[start : start + AUDIT_BATCH_SIZE] for start in range(0, len(pairs), AUDIT_BATCH_SIZE)
    ]
    capacity = asyncio.Semaphore(AUDIT_CONCURRENCY)

    async def classify(batch: list[_AuditPair]) -> set[str]:
        async with capacity:
            response = await client.responses.parse(
                model=model,
                reasoning={"effort": "medium"},
                tools=[],
                tool_choice="none",
                store=False,
                input=cast(
                    ResponseInputParam,
                    [
                        {
                            "role": "developer",
                            "content": (
                                "You are a meticulous semantic-equivalence auditor for game "
                                "dialogue. Prefer meaning over surface wording, follow the supplied "
                                "decision boundary exactly, and emit only the Structured Output. "
                                "Any directed text containing the Unicode replacement character � "
                                "is always a mismatch."
                            ),
                        },
                        {"role": "user", "content": build_mismatch_prompt(batch)},
                    ],
                ),
                text_format=MismatchBatchResult,
            )
        log_openai_usage(
            response.usage,
            operation="direction_mismatch_audit",
            model=model,
            response_id=response.id,
            attempt=1,
            items=len(batch),
        )
        result = response.output_parsed
        assert result is not None, f"{model} returned no parsed mismatch result"
        requested_ids = {pair.id for pair in batch}
        returned_ids = set(result.mismatched_ids)
        assert returned_ids <= requested_ids, (
            f"{model} returned unknown mismatch IDs: {sorted(returned_ids - requested_ids)}"
        )
        return returned_ids

    results = await asyncio.gather(*(classify(batch) for batch in batches))
    return {mismatch_id for result in results for mismatch_id in result}, len(batches)


async def audit_directions(
    database: Path,
    output: Path,
    api_key: str,
    *,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> DirectionAuditSummary:
    """Audit every current direction and write confirmed mismatches as JSON."""
    assert 0 <= similarity_threshold <= 100, "similarity threshold must be between 0 and 100"
    reader = await PipelineReader.open(database)
    client = AsyncOpenAI(api_key=api_key)
    try:
        direction_rows, source_rows = await asyncio.gather(
            reader.directed_lines_table.query().to_pydantic(DirectedLineRecord),
            reader.lines_table.query()
            .select(list(_DialogueText.model_fields))
            .to_pydantic(_DialogueText),
        )
        directions = cast(list[DirectedLineRecord], direction_rows)
        source_texts = {
            row.id: row.text
            for row in cast(list[_DialogueText], source_rows)
            if row.text is not None
        }
        missing = {row.dialogue_line_id for row in directions} - source_texts.keys()
        assert not missing, f"directed lines have no extracted source text: {sorted(missing)[:10]}"
        candidates = suspicious_pairs(directions, source_texts, similarity_threshold)
        mismatch_ids, batch_count = await find_mismatches(client, candidates)
        mismatch_ids.update(pair.id for pair in candidates if "�" in pair.directed)
    finally:
        reader.close()
        await client.close()

    mismatches = [
        DirectionMismatch(
            id=pair.id,
            voice_id=pair.voice_id,
            dialogue_line_id=pair.dialogue_line_id,
            similarity=round(pair.similarity, 2),
            original=pair.original,
            directed=pair.directed,
        )
        for pair in candidates
        if pair.id in mismatch_ids
    ]
    report = DirectionAuditReport(
        created_at=utc_now().isoformat(),
        model=AUDIT_MODEL,
        similarity_threshold=similarity_threshold,
        directed_lines=len(directions),
        rapidfuzz_candidates=len(candidates),
        model_batches=batch_count,
        mismatches=mismatches,
    )
    resolved_output = output.expanduser().resolve()
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return DirectionAuditSummary(
        directed_lines=len(directions),
        rapidfuzz_candidates=len(candidates),
        model_batches=batch_count,
        mismatches=len(mismatches),
        output=str(resolved_output),
    )
