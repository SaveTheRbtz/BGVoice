"""Design and test an Inworld voice for a BGVoice character.

Run as a one-off from the repository root:

    uv run --no-sync --with openai --with httpx --with python-dotenv python tools/voice.py Imoen

The tool reads API credentials from ``.env``, but never writes them to its
artifacts or console output.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import random
import re
import secrets
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from urllib.parse import quote, urlsplit

import httpx
import lancedb
from dotenv import dotenv_values
from lancedb.db import AsyncConnection
from openai import AsyncOpenAI
from openai.types.responses.parsed_response import ParsedResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

INWORLD_DESIGN_URL = "https://api.inworld.ai/voices/v1/voices:design"
INWORLD_VOICES_URL = "https://api.inworld.ai/voices/v1/voices"
INWORLD_TTS_URL = "https://api.inworld.ai/tts/v1/voice"
INWORLD_TTS_MODEL = "inworld-tts-2"

NARRATOR_DISPLAY_NAME = "Narrator"
NARRATOR_LANGUAGE_CODE = "en-GB"
NARRATOR_VOICE_DESCRIPTION = (
    "An old wise male scholar voice with a clear British accent, speaking at a steady pace and "
    "neutral tone. The timbre is warm and resonant, conveying a sense of calm and authority, "
    "suitable for narrations."
)
NARRATOR_PREVIEW_TEXT = (
    "History is a patient teacher. Listen closely as the old stones surrender their secrets, "
    "and let each measured word guide you through the tale."
)
NARRATOR_TAGS = ["bgvoice"]

TTS2_PROMPTING_INSTRUCTIONS = """Your responses will be spoken aloud using inworld-tts-2, which supports
instruction tags — natural language directions in square brackets placed before
the text they apply to.

Use instruction tags to match your delivery to the content. The following are
suggestions; natural language instructions can be used to describe the
appropriate delivery:
- Emotion: [say excitedly], [sound sad], [sound concerned], [sound terrified]
- Articulation: [say with force], [articulate clearly], [say with deliberate pauses]
- Intonation: [say with a falling pitch], [say with a rising pitch]
- Volume: [very quiet], [very loud]
- Pitch: [say in a low tone], [say in a high pitch]
- Range: [say playfully], [say with no pitch variation]
- Speed: [very fast], [very slow]
- Vocal style: [whisper in a hushed style], [give a nasal quality]
- Non-verbals: [laugh], [sigh], [clear throat], [breathe], [cough], [yawn]

For maximum control, combine qualities from multiple categories in a single
natural language instruction. A bare tag like [sound sad] gives the model one
dimension to work with. A fuller instruction like [say sadly with deliberate
pauses in a low voice and hushed style] layers mood, rhythm, pitch, and mode —
producing a more nuanced and convincing performance.

Place the tag at the start of the text it applies to. A tag stays in force
until you change it, so it applies across as many sentences as follow it —
write a new tag only when the delivery should change, and write [reset] where
the delivery should return to normal. For example: [shouting] We need to leave
now! [reset] Do you understand me? Non-verbal tags can also be used inline
where they occur; they produce a sound and do not change the delivery. Do not
apply a tag that contradicts the content of the text. Avoid combining opposing
directions in the same tag — for example, [whisper in a hushed style] and
[very loud] together produce unpredictable results."""

_PROFILE_FIELDS = (
    "dialect",
    "gender",
    "age",
    "emotion",
    "tone",
    "pitch",
    "volume",
    "speed",
    "clarity",
    "fluency",
    "personality",
    "texture",
)
_ASTERISK_DIRECTION = re.compile(r"\*[^*\r\n]+\*")
_INSTRUCTION_TAG = re.compile(r"\[[^\]\r\n]+\]")
_SAFE_SLUG = re.compile(r"[^a-z0-9]+")
_SPEECH_CUE = re.compile(
    r"\b(?:I|me|my|mine|myself|you|your|yours|yourself|yourselves|we|us|our|ours|ourselves)\b",
    re.IGNORECASE,
)
_AUDIO_QUALITY_SUFFIX = "Perfect broadcast quality audio."
_AUDIO_QUALITY_TAIL = re.compile(
    r"\s*perfect broadcast quality audio\.?\s*$",
    re.IGNORECASE,
)
_VOICE_ATTRIBUTE_MAX_LENGTH = 70
_TEXTURE_MAX_LENGTH = 120
_LUNA_CONTEXT_HOPS = 2
_LUNA_CONTEXT_MAX_CHARACTERS = 1200
_FICTIONAL_DIALECT_TERMS = (
    "candlekeep",
    "drow",
    "dwarven",
    "elven",
    "faerun",
    "faerûn",
    "fantasy",
    "forgotten realms",
    "gnomish",
    "halfling",
    "orcish",
    "rashemi",
    "sword coast",
    "underdark",
)

ShortVoiceAttribute = Annotated[
    str,
    Field(
        min_length=1,
        max_length=400,
        description="One complete phrase, ideally at most 70 characters; never truncate words.",
    ),
]
DialectVoiceAttribute = Annotated[
    str,
    Field(
        min_length=1,
        max_length=400,
        description=(
            "One complete concise real-world accent or dialect; never use a fictional place, "
            "people, race, or setting label."
        ),
    ),
]
TextureVoiceAttribute = Annotated[
    str,
    Field(
        min_length=1,
        max_length=400,
        description="One complete concise texture phrase; audio quality is added in code.",
    ),
]


def _shorten_at_word_boundary(value: str, maximum_length: int) -> str:
    """Shorten a model phrase without leaving a partial final word."""
    if len(value) <= maximum_length:
        return value
    shortened = value[: maximum_length + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return shortened or value[:maximum_length]


class StrictModel(BaseModel):
    """Base model for OpenAI Structured Outputs and external responses."""

    model_config = ConfigDict(extra="forbid")


class VoiceProfile(StrictModel):
    """The exact structured profile accepted by Inworld Voice Design."""

    dialect: DialectVoiceAttribute
    gender: ShortVoiceAttribute
    age: ShortVoiceAttribute
    emotion: ShortVoiceAttribute
    tone: ShortVoiceAttribute
    pitch: ShortVoiceAttribute
    volume: ShortVoiceAttribute
    speed: ShortVoiceAttribute
    clarity: ShortVoiceAttribute
    fluency: ShortVoiceAttribute
    personality: ShortVoiceAttribute
    texture: TextureVoiceAttribute

    @field_validator(*_PROFILE_FIELDS[:-1], mode="before")
    @classmethod
    def shorten_attribute(cls, value: object) -> object:
        """Keep the rendered structured profile inside Inworld's input limit."""
        if not isinstance(value, str):
            return value
        cleaned = " ".join(value.split())
        return _shorten_at_word_boundary(cleaned, _VOICE_ATTRIBUTE_MAX_LENGTH)

    @field_validator("texture", mode="before")
    @classmethod
    def add_audio_quality_suffix(cls, value: object) -> object:
        """Canonicalize the final audio-quality direction independently of Sol."""
        if not isinstance(value, str):
            return value
        base = _AUDIO_QUALITY_TAIL.sub("", " ".join(value.split())).rstrip(" ,;:.")
        maximum_base_length = _TEXTURE_MAX_LENGTH - len(_AUDIO_QUALITY_SUFFIX) - 2
        base = _shorten_at_word_boundary(base, maximum_base_length).rstrip(" ,;:.")
        if not base:
            return _AUDIO_QUALITY_SUFFIX
        return f"{base}. {_AUDIO_QUALITY_SUFFIX}"

    @field_validator("*")
    @classmethod
    def clean_attribute(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if ":" in cleaned or "\n" in cleaned or "\r" in cleaned:
            raise ValueError("voice attributes must be single values, not nested fields")
        if not cleaned.isascii() or any(not 32 <= ord(character) <= 126 for character in cleaned):
            raise ValueError("voice attributes must contain only visible printable ASCII")
        return cleaned

    @model_validator(mode="after")
    def reject_fictional_dialect(self) -> Self:
        """Require Sol to translate fictional accent labels into real analogues."""
        dialect = self.dialect.casefold()
        fictional_term = next(
            (term for term in _FICTIONAL_DIALECT_TERMS if term in dialect),
            None,
        )
        if fictional_term is not None:
            raise ValueError(
                f"dialect contains fictional term {fictional_term!r}; use only a real-world accent"
            )
        return self

    def render(self) -> str:
        """Render the user-requested one-attribute-per-line format."""
        values = self.model_dump()
        return "\n".join(
            f"{name}: {values[name]}" for name in _PROFILE_FIELDS if values[name] is not None
        )


class VoiceDesignPlan(StrictModel):
    """Sol's web-researched, API-compatible voice design result."""

    language_code: Annotated[str, Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")]
    profile: VoiceProfile
    preview_text: Annotated[str, Field(min_length=50, max_length=400)]
    research_summary: Annotated[str, Field(min_length=1, max_length=1000)]
    source_urls: Annotated[list[str], Field(min_length=1, max_length=8)]

    @field_validator("source_urls")
    @classmethod
    def validate_source_urls(cls, values: list[str]) -> list[str]:
        for value in values:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"invalid HTTP source URL: {value!r}")
        return values

    @model_validator(mode="after")
    def validate_inworld_limits(self) -> Self:
        prompt = self.profile.render()
        if not 30 <= len(prompt) <= 1000:
            raise ValueError(
                f"rendered Inworld design prompt is {len(prompt)} characters; expected 30-1000"
            )
        return self


class CharacterAbilityScores(StrictModel):
    """Ability scores from the representative CRE used for voice research."""

    strength: int = Field(ge=0, le=0xFF)
    strength_bonus: int = Field(ge=0, le=100)
    intelligence: int = Field(ge=0, le=0xFF)
    wisdom: int = Field(ge=0, le=0xFF)
    dexterity: int = Field(ge=0, le=0xFF)
    constitution: int = Field(ge=0, le=0xFF)
    charisma: int = Field(ge=0, le=0xFF)

    def render(self) -> str:
        strength = str(self.strength)
        if self.strength_bonus:
            exceptional = "00" if self.strength_bonus == 100 else f"{self.strength_bonus:02d}"
            strength = f"{strength}/{exceptional}"
        return (
            f"STR {strength}, DEX {self.dexterity}, CON {self.constitution}, "
            f"INT {self.intelligence}, WIS {self.wisdom}, CHA {self.charisma}"
        )


class CharacterPortrait(StrictModel):
    """Local game portrait metadata plus API-only PNG content."""

    resref: Annotated[str, Field(min_length=1, max_length=8)]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    png: bytes = Field(min_length=1, exclude=True, repr=False)

    def data_url(self) -> str:
        encoded = base64.b64encode(self.png).decode("ascii")
        return f"data:image/png;base64,{encoded}"


class VoiceRepresentative(StrictModel):
    """The voice member with the most attributed NPC dialogue."""

    resource_name: str
    npc_line_count: int = Field(ge=0)
    dialogue_line_count: int = Field(ge=0)
    ability_scores: CharacterAbilityScores
    portrait: CharacterPortrait | None


class CharacterContext(StrictModel):
    """Local BGVoice metadata used to ground voice research."""

    voice_id: str
    display_name: str
    metadata: str
    biography: str | None
    representative: VoiceRepresentative
    variant_resource_names: list[str]
    dialogue_resrefs: list[str]


class DialogueSelection(StrictModel):
    """One randomly selected, directly attributable NPC line."""

    id: str
    run_id: str
    dialogue_resource_name: str
    state_index: int = Field(ge=0)
    strref: int
    text: str
    character_count: int


class DialogueContextTurn(StrictModel):
    """One predecessor state and the transition reply that led onward."""

    run_id: str
    dialogue_resource_name: str
    state_index: int = Field(ge=0)
    transition_index: int | None = Field(default=None, ge=0)
    previous_npc_or_scene_line: str
    player_response: str | None
    source: Annotated[str, Field(pattern=r"^(graph|state_index_fallback)$")]


class NarratorDirectedDialogue(StrictModel):
    """Choose this result when the source is scene narration rather than character speech."""

    speaker: Annotated[
        Literal["narrator"],
        Field(
            description=(
                "Select narrator only when the source text is intended to be spoken as scene, "
                "action, or descriptive narration rather than by the named character."
            )
        ),
    ]
    directed_dialogue: Annotated[
        str,
        Field(
            min_length=1,
            max_length=2000,
            description=(
                "The narrator's complete spoken text, with concise Inworld TTS-2 square-bracket "
                "instruction tags and with source-only asterisks, enclosing parentheses, and "
                "Infinity Engine placeholders removed or naturally rewritten."
            ),
        ),
    ]


class CharacterDirectedDialogue(StrictModel):
    """Choose this result when the named character is the speaker of the source dialogue."""

    speaker: Annotated[
        Literal["character"],
        Field(
            description=(
                "Select character when the named Baldur's Gate character should speak the line, "
                "including dialogue preceded by a brief embedded performance direction."
            )
        ),
    ]
    directed_dialogue: Annotated[
        str,
        Field(
            min_length=1,
            max_length=2000,
            description=(
                "The character's complete spoken text, with concise Inworld TTS-2 square-bracket "
                "instruction tags and with source-only asterisks and Infinity Engine placeholders "
                "removed or naturally rewritten."
            ),
        ),
    ]


DirectedDialogue = Annotated[
    NarratorDirectedDialogue | CharacterDirectedDialogue,
    Field(
        description=(
            "Exactly one speaker-routed TTS direction. Choose the variant from the intended "
            "speaker of the source line, not merely from the presence of punctuation."
        ),
    ),
]


class TTSLinePlan(StrictModel):
    """Luna's structured speaker choice and fully directed Inworld TTS-2 dialogue."""

    result: DirectedDialogue


class InworldPreviewVoice(BaseModel):
    """One draft voice returned by Inworld Voice Design."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    voice_id: str = Field(alias="voiceId")
    preview_text: str = Field(alias="previewText")
    preview_audio: str = Field(alias="previewAudio")


class InworldDesignResponse(BaseModel):
    """Validated subset of the Inworld Voice Design response."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    preview_voices: Annotated[list[InworldPreviewVoice], Field(min_length=1)] = Field(
        alias="previewVoices"
    )


class InworldPublishedVoice(BaseModel):
    """Validated subset of a published Inworld voice resource."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    voice_id: str = Field(alias="voiceId")
    language_code: str | None = Field(default=None, alias="langCode")
    display_name: str = Field(alias="displayName")
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    source: str | None = None


class InworldVoiceListResponse(BaseModel):
    """Validated subset of the current Inworld Voices list response."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    voices: list[InworldPublishedVoice] = Field(default_factory=list)
    next_page_token: str = Field(default="", alias="nextPageToken")


class NarratorVoiceResolution(StrictModel):
    """The deterministic narrator voice selected for synthesis in this run."""

    status: Literal["created", "reused"]
    voice: InworldPublishedVoice


class CharacterVoiceResolution(StrictModel):
    """How the deterministic character voice was resolved for this run."""

    status: Literal["created", "recreated", "reused"]
    voice: InworldPublishedVoice
    replaced_voice_id: str | None = None


class InworldSynthesisResponse(BaseModel):
    """Validated subset of an Inworld synchronous synthesis response."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    audio_content: str = Field(alias="audioContent")
    usage: dict[str, Any] = Field(default_factory=dict)


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _slug(value: str) -> str:
    slug = _SAFE_SLUG.sub("-", value.casefold()).strip("-")
    return slug or "character"


def is_narrator_like_source(text: str) -> bool:
    """Identify source forms that should be offered to Luna for speaker routing."""
    return text.lstrip().startswith(("*", "("))


def _row_value(row: Mapping[str, object], key: str) -> object:
    value = row.get(key)
    if value is None:
        raise RuntimeError(f"local BGVoice row is missing {key!r}")
    return value


async def load_credentials(env_path: Path) -> tuple[str, str]:
    """Load the two API keys without exporting or displaying them."""
    if not env_path.is_file():
        raise FileNotFoundError(f"environment file not found: {env_path}")
    values = await asyncio.to_thread(dotenv_values, env_path)
    openai_key = (values.get("OPENAI_API_KEY") or "").strip()
    inworld_key = (values.get("INWORLD_API_KEY") or "").strip()
    missing = [
        name
        for name, value in (
            ("OPENAI_API_KEY", openai_key),
            ("INWORLD_API_KEY", inworld_key),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"missing required .env entries: {', '.join(missing)}")
    return openai_key, inworld_key


async def _latest_attribution_run_id(database: AsyncConnection) -> str:
    table = await database.open_table("extraction_runs")
    arrow = await (
        table.query()
        .where(
            "run_kind = 'attribution' AND (status = 'complete' OR status = 'complete_with_errors')"
        )
        .select(["id", "completed_at"])
        .to_arrow()
    )
    rows = arrow.to_pylist()
    if not rows:
        raise RuntimeError("the BGVoice database has no completed attribution run")
    latest = max(rows, key=lambda row: str(row.get("completed_at") or ""))
    return str(_row_value(latest, "id"))


async def _character_voice_row(
    database: AsyncConnection, character: str, run_id: str
) -> dict[str, Any]:
    table = await database.open_table("voice_resources")
    arrow = await (
        table.query()
        .where(f"run_id = {_sql_string(run_id)}")
        .select(
            [
                "voice_id",
                "display_name",
                "prompt",
                "variant_resource_names",
                "dialogue_resrefs",
            ]
        )
        .to_arrow()
    )
    matches = [
        row
        for row in arrow.to_pylist()
        if str(row.get("display_name") or "").casefold() == character.casefold()
    ]
    if not matches:
        raise RuntimeError(f"no attributed voice named {character!r} exists in the database")
    return max(
        matches,
        key=lambda row: (
            len(row.get("variant_resource_names") or []),
            len(row.get("dialogue_resrefs") or []),
            str(row.get("voice_id") or ""),
        ),
    )


def _metadata_and_biography(prompt: str) -> tuple[str, str | None]:
    metadata, separator, biography = prompt.partition("\n\nBiography:\n")
    cleaned_biography = biography.strip() if separator else ""
    return metadata.strip(), cleaned_biography or None


async def _voice_representative(
    database: AsyncConnection,
    variant_resource_names: list[str],
    run_id: str,
) -> VoiceRepresentative:
    """Choose the highest-NPC-line CRE and load its stats and best portrait."""
    if not variant_resource_names:
        raise RuntimeError("the selected voice has no character variants")
    variant_filter = ", ".join(_sql_string(value) for value in variant_resource_names)
    characters, attributions, dialogues, portraits = await asyncio.gather(
        database.open_table("characters"),
        database.open_table("character_dialogues"),
        database.open_table("dialogues"),
        database.open_table("portrait_images"),
    )
    character_arrow, attribution_arrow = await asyncio.gather(
        characters.query()
        .where(f"resource_name IN ({variant_filter})")
        .select(["resource_name", "detail"])
        .to_arrow(),
        attributions.query()
        .where(f"run_id = {_sql_string(run_id)} AND character_resource_name IN ({variant_filter})")
        .select(["character_resource_name", "resolved_dialogue_resource_names"])
        .to_arrow(),
    )
    character_rows = [row for row in character_arrow.to_pylist() if row.get("detail")]
    if not character_rows:
        raise RuntimeError("none of the selected voice's character variants has extracted detail")
    attribution_rows = attribution_arrow.to_pylist()
    attribution_by_character = {
        str(row.get("character_resource_name") or "").casefold(): row for row in attribution_rows
    }
    dialogue_names = sorted(
        {
            str(resource_name)
            for row in attribution_rows
            for resource_name in row.get("resolved_dialogue_resource_names") or []
        },
        key=str.casefold,
    )
    dialogue_by_name: dict[str, dict[str, Any]] = {}
    if dialogue_names:
        dialogue_filter = ", ".join(_sql_string(value) for value in dialogue_names)
        dialogue_arrow = await (
            dialogues.query()
            .where(f"resource_name IN ({dialogue_filter})")
            .select(["resource_name", "detail"])
            .to_arrow()
        )
        dialogue_by_name = {
            str(row.get("resource_name") or "").casefold(): row
            for row in dialogue_arrow.to_pylist()
        }

    requested_portraits = sorted(
        {
            str(resref)
            for row in character_rows
            for resref in (
                (row.get("detail") or {}).get("large_portrait"),
                (row.get("detail") or {}).get("small_portrait"),
            )
            if resref
        },
        key=str.casefold,
    )
    available_portraits: set[str] = set()
    if requested_portraits:
        portrait_filter = ", ".join(_sql_string(value) for value in requested_portraits)
        portrait_arrow = await (
            portraits.query().where(f"resref IN ({portrait_filter})").select(["resref"]).to_arrow()
        )
        available_portraits = {
            str(row.get("resref") or "").casefold() for row in portrait_arrow.to_pylist()
        }

    ranked: list[tuple[int, int, str | None, dict[str, Any]]] = []
    for character_row in character_rows:
        resource_name = str(_row_value(character_row, "resource_name"))
        detail = character_row.get("detail") or {}
        attribution = attribution_by_character.get(resource_name.casefold(), {})
        resolved_dialogues = attribution.get("resolved_dialogue_resource_names") or []
        npc_line_count = 0
        dialogue_line_count = 0
        for dialogue_name in resolved_dialogues:
            dialogue = dialogue_by_name.get(str(dialogue_name).casefold(), {})
            dialogue_detail = dialogue.get("detail") or {}
            npc_line_count += int(dialogue_detail.get("npc_line_count") or 0)
            dialogue_line_count += int(dialogue_detail.get("dialogue_line_count") or 0)
        portrait_resref = next(
            (
                str(resref)
                for resref in (detail.get("large_portrait"), detail.get("small_portrait"))
                if resref and str(resref).casefold() in available_portraits
            ),
            None,
        )
        ranked.append((npc_line_count, dialogue_line_count, portrait_resref, character_row))

    npc_line_count, dialogue_line_count, portrait_resref, representative_row = min(
        ranked,
        key=lambda item: (
            -item[0],
            -item[1],
            item[2] is None,
            str(item[3].get("resource_name") or "").casefold(),
            str(item[3].get("resource_name") or ""),
        ),
    )
    representative_detail = representative_row.get("detail") or {}
    portrait: CharacterPortrait | None = None
    if portrait_resref is not None:
        portrait_arrow = await (
            portraits.query()
            .where(f"resref = {_sql_string(portrait_resref)}")
            .select(["resref", "width", "height", "png"])
            .to_arrow()
        )
        portrait_rows = portrait_arrow.to_pylist()
        if len(portrait_rows) != 1:
            raise RuntimeError(
                f"portrait {portrait_resref!r} resolved to {len(portrait_rows)} rows"
            )
        portrait = CharacterPortrait.model_validate(portrait_rows[0])
    return VoiceRepresentative(
        resource_name=str(_row_value(representative_row, "resource_name")),
        npc_line_count=npc_line_count,
        dialogue_line_count=dialogue_line_count,
        ability_scores=CharacterAbilityScores.model_validate(
            _row_value(representative_detail, "base_attributes")
        ),
        portrait=portrait,
    )


async def _dialogue_candidates(
    database: AsyncConnection,
    dialogue_resrefs: list[str],
    *,
    speaker_name: str,
    minimum_characters: int,
    maximum_characters: int,
) -> list[DialogueSelection]:
    if not dialogue_resrefs:
        raise RuntimeError("the selected voice has no attributed dialogues")
    resref_filter = ", ".join(_sql_string(value) for value in dialogue_resrefs)
    dialogues = await database.open_table("dialogues")
    dialogue_arrow = await (
        dialogues.query()
        .where(f"resref IN ({resref_filter})")
        .select(["resource_name", "extraction"])
        .to_arrow()
    )
    dialogue_rows = [
        row
        for row in dialogue_arrow.to_pylist()
        if (row.get("extraction") or {}).get("status") == "complete"
    ]
    if not dialogue_rows:
        raise RuntimeError("none of the selected voice's dialogues completed extraction")

    dialogue_names = [str(_row_value(row, "resource_name")) for row in dialogue_rows]
    dialogue_run_ids = sorted(
        {
            str(_row_value(row["extraction"], "run_id"))
            for row in dialogue_rows
            if row.get("extraction")
        }
    )
    name_filter = ", ".join(_sql_string(value) for value in dialogue_names)
    run_filter = ", ".join(_sql_string(value) for value in dialogue_run_ids)
    lines = await database.open_table("dialogue_lines")
    line_arrow = await (
        lines.query()
        .where(
            f"run_id IN ({run_filter}) AND dialogue_resource_name IN ({name_filter}) "
            "AND line_kind = 'npc'"
        )
        .select(
            [
                "id",
                "run_id",
                "dialogue_resource_name",
                "state_index",
                "strref",
                "text",
            ]
        )
        .to_arrow()
    )

    candidates: list[DialogueSelection] = []
    for row in line_arrow.to_pylist():
        text = str(row.get("text") or "").strip()
        if not minimum_characters <= len(text) <= maximum_characters:
            continue
        narrator_like = is_narrator_like_source(text)
        if any(mark in text for mark in ("[", "]", "^")):
            continue
        if not narrator_like:
            if "(" in text or ")" in text:
                continue
            spoken_source = _ASTERISK_DIRECTION.sub("", text)
            if re.search(rf"\b{re.escape(speaker_name)}\b", spoken_source, re.IGNORECASE):
                continue
            if not _SPEECH_CUE.search(text):
                continue
        candidates.append(
            DialogueSelection(
                id=str(_row_value(row, "id")),
                run_id=str(_row_value(row, "run_id")),
                dialogue_resource_name=str(_row_value(row, "dialogue_resource_name")),
                state_index=int(_row_value(row, "state_index")),
                strref=int(_row_value(row, "strref")),
                text=text,
                character_count=len(text),
            )
        )
    if not candidates:
        raise RuntimeError(
            "no clean NPC dialogue lines matched the requested "
            f"{minimum_characters}-{maximum_characters} character range"
        )
    return candidates


def _dialogue_resref(resource_name: str) -> str:
    """Return the engine resref used by transition destinations."""
    return resource_name[:-4] if resource_name.casefold().endswith(".dlg") else resource_name


def _context_line(value: object) -> str | None:
    """Normalize a stored dialogue line for compact prompt context."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


async def _context_turn_from_state(
    database: AsyncConnection,
    *,
    run_id: str,
    dialogue_resource_name: str,
    state_index: int,
    transition_index: int | None,
    source: str,
) -> DialogueContextTurn | None:
    """Load the source NPC state and its selected player reply, if present."""
    lines = await database.open_table("dialogue_lines")
    arrow = await (
        lines.query()
        .where(
            f"run_id = {_sql_string(run_id)} "
            f"AND dialogue_resource_name = {_sql_string(dialogue_resource_name)} "
            f"AND state_index = {state_index}"
        )
        .select(["id", "line_kind", "transition_index", "text"])
        .to_arrow()
    )
    rows = sorted(arrow.to_pylist(), key=lambda row: str(row.get("id") or ""))
    npc_text = next(
        (
            text
            for row in rows
            if str(row.get("line_kind") or "") == "npc"
            and (text := _context_line(row.get("text"))) is not None
        ),
        None,
    )
    if npc_text is None:
        return None
    player_text = next(
        (
            text
            for row in rows
            if transition_index is not None
            and str(row.get("line_kind") or "") == "player"
            and row.get("transition_index") == transition_index
            and (text := _context_line(row.get("text"))) is not None
        ),
        None,
    )
    return DialogueContextTurn(
        run_id=run_id,
        dialogue_resource_name=dialogue_resource_name,
        state_index=state_index,
        transition_index=transition_index,
        previous_npc_or_scene_line=npc_text,
        player_response=player_text,
        source=source,
    )


async def _graph_predecessor(
    database: AsyncConnection,
    *,
    target_dialogue_resource_name: str,
    target_state_index: int,
    visited: set[tuple[str, int]],
) -> DialogueContextTurn | None:
    """Choose one deterministic valid inbound edge to the target state."""
    transitions = await database.open_table("dialogue_transitions")
    arrow = await (
        transitions.query()
        .where(f"next_state_index = {target_state_index}")
        .select(
            [
                "id",
                "run_id",
                "dialogue_resource_name",
                "state_index",
                "transition_index",
                "next_dialog",
            ]
        )
        .to_arrow()
    )
    target_name = target_dialogue_resource_name.casefold()
    target_resref = _dialogue_resref(target_dialogue_resource_name).casefold()
    incoming: list[dict[str, Any]] = []
    for edge in arrow.to_pylist():
        source_name = str(edge.get("dialogue_resource_name") or "")
        next_dialog = edge.get("next_dialog")
        same_dialogue = next_dialog is None and source_name.casefold() == target_name
        cross_dialogue = next_dialog is not None and str(next_dialog).casefold() == target_resref
        if same_dialogue or cross_dialogue:
            incoming.append(edge)

    incoming.sort(
        key=lambda edge: (
            str(edge.get("dialogue_resource_name") or "").casefold() != target_name,
            str(edge.get("dialogue_resource_name") or "").casefold(),
            int(edge.get("state_index") or 0),
            int(edge.get("transition_index") or 0),
            str(edge.get("id") or ""),
        )
    )
    for edge in incoming:
        source_name = str(_row_value(edge, "dialogue_resource_name"))
        source_state = int(_row_value(edge, "state_index"))
        if (source_name.casefold(), source_state) in visited:
            continue
        turn = await _context_turn_from_state(
            database,
            run_id=str(_row_value(edge, "run_id")),
            dialogue_resource_name=source_name,
            state_index=source_state,
            transition_index=int(_row_value(edge, "transition_index")),
            source="graph",
        )
        if turn is not None:
            return turn
    return None


async def _state_index_fallback(
    database: AsyncConnection,
    *,
    run_id: str,
    target_dialogue_resource_name: str,
    target_state_index: int,
    visited: set[tuple[str, int]],
) -> DialogueContextTurn | None:
    """Use the preceding state only when no graph predecessor can be resolved."""
    if target_state_index == 0:
        return None
    previous_state = target_state_index - 1
    key = (target_dialogue_resource_name.casefold(), previous_state)
    if key in visited:
        return None
    return await _context_turn_from_state(
        database,
        run_id=run_id,
        dialogue_resource_name=target_dialogue_resource_name,
        state_index=previous_state,
        transition_index=None,
        source="state_index_fallback",
    )


async def load_dialogue_history(
    database_path: Path,
    line: DialogueSelection,
    *,
    max_hops: int = _LUNA_CONTEXT_HOPS,
) -> list[DialogueContextTurn]:
    """Resolve up to two predecessor turns along one valid dialogue-graph path."""
    if max_hops < 0:
        raise ValueError("max_hops cannot be negative")
    if max_hops == 0:
        return []
    database = await lancedb.connect_async(database_path)
    history_nearest_first: list[DialogueContextTurn] = []
    target_run_id = line.run_id
    target_dialogue = line.dialogue_resource_name
    target_state = line.state_index
    visited = {(target_dialogue.casefold(), target_state)}
    try:
        for _hop in range(max_hops):
            turn = await _graph_predecessor(
                database,
                target_dialogue_resource_name=target_dialogue,
                target_state_index=target_state,
                visited=visited,
            )
            if turn is None:
                turn = await _state_index_fallback(
                    database,
                    run_id=target_run_id,
                    target_dialogue_resource_name=target_dialogue,
                    target_state_index=target_state,
                    visited=visited,
                )
            if turn is None:
                break
            history_nearest_first.append(turn)
            target_run_id = turn.run_id
            target_dialogue = turn.dialogue_resource_name
            target_state = turn.state_index
            visited.add((target_dialogue.casefold(), target_state))
    finally:
        database.close()
    return list(reversed(history_nearest_first))


async def load_character_context(
    database_path: Path,
    character: str,
    *,
    minimum_characters: int,
    maximum_characters: int,
) -> tuple[CharacterContext, list[DialogueSelection]]:
    """Read the canonical local voice and its eligible dialogue asynchronously."""
    if not database_path.is_dir():
        raise FileNotFoundError(f"BGVoice database not found: {database_path}")
    database = await lancedb.connect_async(database_path)
    try:
        run_id = await _latest_attribution_run_id(database)
        voice = await _character_voice_row(database, character, run_id)
        variant_resource_names = [str(value) for value in voice.get("variant_resource_names") or []]
        dialogue_resrefs = [str(value) for value in voice.get("dialogue_resrefs") or []]
        representative, candidates = await asyncio.gather(
            _voice_representative(database, variant_resource_names, run_id),
            _dialogue_candidates(
                database,
                dialogue_resrefs,
                speaker_name=character,
                minimum_characters=minimum_characters,
                maximum_characters=maximum_characters,
            ),
        )
    finally:
        database.close()

    metadata, biography = _metadata_and_biography(str(_row_value(voice, "prompt")))
    return (
        CharacterContext(
            voice_id=str(_row_value(voice, "voice_id")),
            display_name=str(_row_value(voice, "display_name")),
            metadata=metadata,
            biography=biography,
            representative=representative,
            variant_resource_names=variant_resource_names,
            dialogue_resrefs=dialogue_resrefs,
        ),
        candidates,
    )


def build_voice_design_prompt(context: CharacterContext) -> str:
    """Create Sol's character research and voice-direction prompt."""
    biography = (
        f"\n\n{context.display_name} biography:\n{context.biography}"
        if context.biography is not None
        else f"\n\n{context.display_name} biography: unavailable."
    )
    portrait = (
        f"A local game portrait of {context.display_name} is attached."
        if context.representative.portrait is not None
        else f"No local game portrait is available for {context.display_name}."
    )
    return f"""Design an original synthetic voice for {context.display_name} from Baldur's Gate.

Combine your internal model knowledge with current web research. Use web search at least once to
find reliable character biography or description material and vocal-characterization evidence.
Treat the local extracted game metadata below as authoritative for this installation. Reconcile
campaign progression such as class changes rather than treating it as a contradiction. Do not
name, clone, or instruct imitation of any real performer; translate evidence into abstract vocal
qualities only.

Local metadata:
{context.metadata}{biography}

Additional local character evidence:
- Ability scores: {context.representative.ability_scores.render()}
- Portrait: {portrait}

## Voice Description Best Practices

The voice description helps the model understand the type of voice you want to generate. The
following best practices will help you write descriptions that produce better voices:

1. **Be specific in your description** - Vague descriptions like "a fun voice" may produce less
   consistent results. Include details about age, gender, language (if not English), accent, pitch,
   pace, timbre, tone, and emotional quality. We generally recommend structuring your description
   in this order: *Distinctive Qualities → Gender → Language / Accent → Age → Tone →
   Delivery Style → Pacing → Additional Qualities → Audio Quality*. For example:
   > "A soothing, calming female voice with soft American accent, 30-45 years old. Gentle, flowing
   > delivery with natural pauses and smooth transitions. Warm, peaceful tone that creates
   > relaxation without sounding robotic. Perfect broadcast quality audio."
2. **Be specific with age** - If more general terms like "young" and "old" are not producing the
   desired voice, use more specific age ranges like "mid-20s to early 30s" or "late 60s to early
   70s".
   - For child voices, try specifying exact ages (e.g., "8-10 years old") and emphasize "natural"
     and "age-appropriate" to avoid over-cutesy results.
   - For elderly voices, include both the age range and specific texture descriptors ("gravelly,"
     "weathered") along with pacing cues ("slower, deliberate").
3. **For regional accents, specify the city or region** - For regional accents, always include the
   specific city or region. For example, write "Boston accent" rather than "Northeast accent."
4. **Use only real-world accents and dialects** - The dialect field must never name a fictional
   place, people, race, culture, language, or setting. When character evidence uses a fictional
   accent, research and select the closest real-world vocal analogue. This describes sound only;
   it does not claim that the character has that real-world nationality or identity.
   - Example fictional evidence: `dialect: strong Rashemi accent`
   - Replace it with: `dialect: English with a strong Russian accent`
   Never return "Rashemi accent," "Sword Coast accent," "drow accent," or similar fictional labels.
5. **Describe vocal texture in the middle** - Place descriptions of the vocal texture and timbre
   (e.g., "raspy," "breathy," "nasally") in the middle of your voice description, never at the end.
   Use modifiers like "slight," "subtle," or "natural" to prevent over-exaggeration.
6. **End with audio quality** - For the clearest audio quality, include the phrase "Perfect
   broadcast quality audio." at the end of your description. This can be especially helpful if the
   voice includes descriptions like "gravelly", "breathy", or "scratchy" that may be misinterpreted
   as audio degradation.
7. **Avoid conflicting descriptors** - Don't use conflicting descriptors (e.g., "fast-paced" with
   "slow, deliberate"), as that may confuse the model.

Pirate structured voice example:
dialect: west country english
gender: male
age: adult
emotion: amused and lighthearted
tone: performative and theatrical
pitch: medium-low male pitch with varied intonation for emphasis
volume: loud and projecting
speed: slow and deliberate, with dramatic pauses
clarity: moderate, some words are slurred or mumbled
fluency: fluent but interrupted by laughter
personality: playful, confident, and a bit mischievous
texture: harsh and raspy, with a gravelly, weathered quality
"""


def build_voice_design_content(
    context: CharacterContext,
    prompt: str,
) -> list[dict[str, object]]:
    """Build Sol's multimodal user content without exposing image bytes in text artifacts."""
    content: list[dict[str, object]] = [{"type": "input_text", "text": prompt}]
    portrait = context.representative.portrait
    if portrait is not None:
        content.append(
            {
                "type": "input_image",
                "image_url": portrait.data_url(),
                "detail": "high",
            }
        )
    return content


def _response_used_web_search(response: ParsedResponse[VoiceDesignPlan]) -> bool:
    return any(str(getattr(item, "type", "")).startswith("web_search") for item in response.output)


async def create_voice_design_plan(
    client: AsyncOpenAI,
    context: CharacterContext,
    *,
    model: str,
) -> tuple[VoiceDesignPlan, str]:
    """Ask Sol for a web-researched Pydantic voice design."""
    prompt = build_voice_design_prompt(context)
    errors: list[str] = []
    for _attempt in range(3):
        retry_note = ""
        if errors:
            retry_note = (
                "\nThe previous result failed local compatibility validation: "
                + errors[-1]
                + " Correct that issue while following every original requirement."
            )
        user_content = build_voice_design_content(context, prompt + retry_note)
        try:
            response = await client.responses.parse(
                model=model,
                reasoning={"effort": "medium"},
                tools=[{"type": "web_search"}],
                tool_choice="required",
                max_tool_calls=4,
                include=["web_search_call.action.sources"],
                store=False,
                input=[
                    {
                        "role": "developer",
                        "content": (
                            "You are an expert casting director and voice designer. "
                            "Research carefully, distinguish fact from inference, and emit only "
                            "the supplied Structured Output."
                        ),
                    },
                    {"role": "user", "content": user_content},
                ],
                text_format=VoiceDesignPlan,
            )
            plan = response.output_parsed
            if plan is None:
                raise RuntimeError("Sol returned no parsed voice design")
            if not _response_used_web_search(response):
                raise RuntimeError("Sol did not use the required web search tool")
            return plan, prompt
        except (ValidationError, ValueError, RuntimeError) as error:
            errors.append(str(error)[:500])
    raise RuntimeError("Sol could not produce an Inworld-compatible voice design: " + errors[-1])


def choose_dialogue_line(
    candidates: list[DialogueSelection],
    seed: int | None,
    dialogue_id: str | None = None,
) -> DialogueSelection:
    """Choose an eligible line randomly, by seed, or by its exact persisted ID."""
    if dialogue_id is not None:
        matches = [candidate for candidate in candidates if candidate.id == dialogue_id]
        if len(matches) != 1:
            raise ValueError(
                f"--dialogue-id matched {len(matches)} eligible lines; expected exactly one: "
                f"{dialogue_id}"
            )
        return matches[0]
    if seed is None:
        return secrets.choice(candidates)
    return random.Random(seed).choice(candidates)


def _format_dialogue_history(history: Sequence[DialogueContextTurn]) -> str:
    """Render graph history without exposing resource or state identifiers to Luna."""
    lines = ["Unspoken scene context:"]
    multiple_turns = len(history) > 1
    for index, turn in enumerate(history, start=1):
        if multiple_turns:
            proximity = "immediate" if index == len(history) else "earlier"
            lines.append(f"Context turn {index} ({proximity}):")
        lines.append(f"Previous NPC/scene line: {turn.previous_npc_or_scene_line}")
        player_response = turn.player_response or "none (automatic scene transition)"
        lines.append(f"Player response: {player_response}")
    return "\n".join(lines)


def render_dialogue_history(
    history: Sequence[DialogueContextTurn],
    *,
    maximum_characters: int = _LUNA_CONTEXT_MAX_CHARACTERS,
) -> str:
    """Prefer the nearest complete graph turns and bound Luna-only context."""
    if maximum_characters < 1:
        raise ValueError("maximum_characters must be positive")
    selected = list(history[-_LUNA_CONTEXT_HOPS:])
    if not selected:
        return ""
    rendered = _format_dialogue_history(selected)
    while len(rendered) > maximum_characters and len(selected) > 1:
        selected.pop(0)
        rendered = _format_dialogue_history(selected)
    if len(rendered) <= maximum_characters:
        return rendered

    turn = selected[-1]
    player_response = turn.player_response or "none (automatic scene transition)"
    fixed_length = len("Unspoken scene context:\nPrevious NPC/scene line: \nPlayer response: ")
    available = max(1, maximum_characters - fixed_length)
    if turn.player_response is None:
        npc_budget = max(1, available - len(player_response))
        player_budget = len(player_response)
    else:
        player_budget = max(1, available // 3)
        npc_budget = max(1, available - player_budget)
    shortened = turn.model_copy(
        update={
            "previous_npc_or_scene_line": _shorten_at_word_boundary(
                turn.previous_npc_or_scene_line, npc_budget
            ),
            "player_response": (
                None
                if turn.player_response is None
                else _shorten_at_word_boundary(turn.player_response, player_budget)
            ),
        }
    )
    return _format_dialogue_history([shortened])[:maximum_characters]


def build_tts2_prompt(
    line: DialogueSelection,
    context: CharacterContext,
    dialogue_history: Sequence[DialogueContextTurn] = (),
) -> str:
    """Create Luna's speaker-routing and direction prompt from the Inworld TTS-2 guide."""
    rendered_history = render_dialogue_history(dialogue_history)
    history_section = ""
    if rendered_history:
        history_section = f"""The following scene context is unspoken evidence for interpreting
the target dialogue's meaning, emotion, and delivery only. Do not quote, paraphrase, mention, or
otherwise include any of this context in the output. Direct only the target dialogue.

{rendered_history}

"""
    return f"""Route and direct the following attributed {context.display_name} dialogue from
Baldur's Gate. The stored NPC line may be either actual character speech or authorial scene
narration that should use a separate narrator voice.

{TTS2_PROMPTING_INSTRUCTIONS}

Rewrite the following Baldur's Gate dialogue so it contains no Infinity Engine placeholder tokens.

Replace every angle-bracket token, such as <CHARNAME>, <GABBER>, <PLAYER2>, <PRO_HESHE>,
<PRO_HIMHER>, <PRO_HISHER>, <PRO_LADYLORD>, <RACE>, or similar, by naturally rewriting the
surrounding sentence.

Rules:
- Never include an angle-bracket token in the result.
- Do not invent character names, genders, races, classes, titles, or party members.
- For <CHARNAME> used as direct address, usually remove it or rewrite the address using “you.”
- Rewrite gendered pronoun tokens using “they,” “them,” “their,” or a natural sentence that
  avoids the pronoun.
- Rewrite party-slot tokens using neutral wording such as “your companion” only when the
  reference is necessary.
- Prefer rewriting the entire clause over inserting an awkward mechanical replacement.
- Preserve the original meaning, personality, and spoken wording as closely as possible.

Placeholder examples:
Input: <CHARNAME>, wait! I need to speak with you.
Output: Wait! I need to speak with you.

Input: I knew you would return, <CHARNAME>.
Output: I knew you would return.

Input: Does <PRO_HESHE> understand what is happening?
Output: Do they understand what is happening?

Input: Tell <PLAYER2> to remain here.
Output: Tell your companion to remain here.

First decide who is intended to speak the target line:

- Choose the narrator result when the line is primarily authorial prose describing a scene,
  action, passage of time, dream, or visual event rather than words spoken by
  {context.display_name}. Fully enclosing asterisks or parentheses are strong evidence of
  narration, but punctuation alone is not decisive. Strip those source-only wrappers and retain
  the narrative prose as spoken narrator text.
- Choose the character result when direct speech by {context.display_name} is the main content.
  A brief stage direction such as *sighs* or *whispering* before actual speech does not make the
  line narration.
- Use exactly one speaker for the whole result. Never include the speaker choice in the spoken
  text, and never copy the unspoken scene context into it.

Narrator routing example:
Input: *The ancient doors grind open, revealing a silent hall beyond.*
Output: {{"result":{{"speaker":"narrator","directed_dialogue":"[narrate calmly with deliberate pacing and a warm, neutral tone] The ancient doors grind open, revealing a silent hall beyond."}}}}

For a character result, treat embedded asterisk-delimited text such as *sighs*, *whispering*, or
*looks away* as performance or stage directions rather than spoken dialogue.

- Convert audible actions and vocal directions into concise, neutral instruction tags in square
  brackets.
- Remove purely visual actions that cannot be conveyed through voice.
- Do not infer additional emotion from a visual action. For example, remove *looks away* instead
  of rewriting it as [sound ashamed].

Asterisk examples:
Input: *sigh* Right.
Output: [sigh] Right.

Input: *whispering* We need to leave.
Output: [speak quietly] We need to leave.

Input: *Imoen looks nervously toward the door.* We should go.
Output: We should go.

Input: Oh, *I* know that!
Output: [emphasize “I”] Oh, I know that!

After rewriting the source text, use the TTS-2 instruction-tag guide above to direct its delivery.
Do not add spoken content, markdown, emojis, or enclosing quotation marks inside directed_dialogue.
Use character metadata only to inform character delivery; never turn it into spoken content or use
it to invent runtime-dependent details. Return the structured speaker choice and its rewritten,
TTS-directed dialogue.

Character metadata:
{context.metadata}

{history_section}Target dialogue to direct:
{line.text}
"""


def validate_directed_text(
    original: str,
    directed: str,
    dialogue_history: Sequence[DialogueContextTurn] = (),
    *,
    speaker: Literal["narrator", "character"],
) -> None:
    """Ensure Luna removed source-only constructs from the spoken result."""
    if not original.strip():
        raise ValueError("original dialogue is empty")
    if not directed.strip():
        raise ValueError("directed dialogue is empty")
    if "<" in directed or ">" in directed:
        raise ValueError("directed dialogue still contains an angle-bracket placeholder")
    if "*" in directed:
        raise ValueError("directed dialogue still contains an asterisk-delimited direction")
    if "```" in directed:
        raise ValueError("directed dialogue contains a markdown code fence")
    if "�" in directed:
        raise ValueError("directed dialogue contains a Unicode replacement character")
    stripped_directed = directed.strip()
    if (
        speaker == "narrator"
        and stripped_directed.startswith("(")
        and stripped_directed.endswith(")")
    ):
        raise ValueError("narrator dialogue still has source-only enclosing parentheses")
    normalized_original = " ".join(original.split()).casefold()
    normalized_directed = " ".join(_INSTRUCTION_TAG.sub("", directed).split()).casefold()
    for turn in dialogue_history:
        for value in (turn.previous_npc_or_scene_line, turn.player_response):
            normalized_context = " ".join((value or "").split()).casefold()
            if (
                len(normalized_context) >= 30
                and normalized_context not in normalized_original
                and normalized_context in normalized_directed
            ):
                raise ValueError("directed dialogue repeats unspoken scene context")


async def create_tts_line_plan(
    client: AsyncOpenAI,
    line: DialogueSelection,
    context: CharacterContext,
    dialogue_history: Sequence[DialogueContextTurn] = (),
    *,
    model: str,
) -> tuple[TTSLinePlan, str]:
    """Ask Luna to choose the speaker and direct the line under a strict Pydantic schema."""
    prompt = build_tts2_prompt(line, context, dialogue_history)
    errors: list[str] = []
    for _attempt in range(3):
        retry_note = ""
        if errors:
            retry_note = (
                "\nThe previous result failed validation: "
                + errors[-1]
                + " Return a corrected structured speaker result whose directed_dialogue removes "
                "source-only wrappers, placeholder tokens, and asterisk directions as instructed."
            )
        try:
            response = await client.responses.parse(
                model=model,
                reasoning={"effort": "medium"},
                tools=[],
                tool_choice="none",
                store=False,
                input=[
                    {
                        "role": "developer",
                        "content": (
                            "You direct expressive game dialogue for Inworld TTS-2. "
                            "Choose the intended narrator or character speaker, then obey the "
                            "placeholder and stage-direction rewriting rules exactly. Return only "
                            "the supplied Structured Output."
                        ),
                    },
                    {"role": "user", "content": prompt + retry_note},
                ],
                text_format=TTSLinePlan,
            )
            plan = response.output_parsed
            if plan is None:
                raise RuntimeError("Luna returned no parsed TTS-2 line plan")
            result = plan.result
            validate_directed_text(
                line.text,
                result.directed_dialogue,
                dialogue_history,
                speaker=result.speaker,
            )
            return plan, prompt
        except (ValidationError, ValueError, RuntimeError) as error:
            errors.append(str(error)[:500])
    raise RuntimeError("Luna could not route and direct the selected line: " + errors[-1])


def _inworld_authorization(api_key: str) -> str:
    return api_key if api_key.casefold().startswith("basic ") else f"Basic {api_key}"


async def _inworld_get(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await client.get(
        url,
        headers={"Authorization": _inworld_authorization(api_key)},
        params=params,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        body = response.text[:1000]
        raise RuntimeError(
            f"Inworld request failed with HTTP {response.status_code}: {body}"
        ) from error
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Inworld returned a non-object JSON response")
    return data


async def _inworld_post(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = await client.post(
        url,
        headers={
            "Authorization": _inworld_authorization(api_key),
            "Content-Type": "application/json",
        },
        json=payload,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        body = response.text[:1000]
        raise RuntimeError(
            f"Inworld request failed with HTTP {response.status_code}: {body}"
        ) from error
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Inworld returned a non-object JSON response")
    return data


async def design_inworld_voice(
    client: httpx.AsyncClient,
    api_key: str,
    *,
    language_code: str,
    design_prompt: str,
    preview_text: str,
) -> InworldDesignResponse:
    """Generate one draft voice preview."""
    data = await _inworld_post(
        client,
        INWORLD_DESIGN_URL,
        api_key,
        {
            "languageCode": language_code,
            "designPrompt": design_prompt,
            "previewText": preview_text,
            "voiceDesignConfig": {"numberOfSamples": 1},
        },
    )
    return InworldDesignResponse.model_validate(data)


async def publish_inworld_voice(
    client: httpx.AsyncClient,
    api_key: str,
    preview: InworldPreviewVoice,
    *,
    display_name: str,
    description: str,
    tags: Sequence[str],
) -> InworldPublishedVoice:
    """Publish the selected draft so it can synthesize TTS."""
    voice_url = (
        "https://api.inworld.ai/voices/v1/voices/" + quote(preview.voice_id, safe="") + ":publish"
    )
    data = await _inworld_post(
        client,
        voice_url,
        api_key,
        {
            "displayName": display_name,
            "description": description,
            "tags": list(tags),
        },
    )
    return InworldPublishedVoice.model_validate(data)


async def list_inworld_workspace_voices(
    client: httpx.AsyncClient,
    api_key: str,
) -> list[InworldPublishedVoice]:
    """List every workspace-owned designed/cloned voice through the current Voices API."""
    voices: list[InworldPublishedVoice] = []
    page_token = ""
    while True:
        params: dict[str, Any] = {
            "filter": 'source = "IVC"',
            "orderBy": "display_name asc",
            "pageSize": 2000,
        }
        if page_token:
            params["pageToken"] = page_token
        data = await _inworld_get(
            client,
            INWORLD_VOICES_URL,
            api_key,
            params=params,
        )
        page = InworldVoiceListResponse.model_validate(data)
        voices.extend(page.voices)
        page_token = page.next_page_token
        if not page_token:
            return voices


def select_named_inworld_voice(
    voices: Sequence[InworldPublishedVoice],
    display_name: str,
    *,
    preferred_description: str | None = None,
) -> InworldPublishedVoice | None:
    """Choose one deterministic workspace voice with the exact display name."""
    matches = [
        voice for voice in voices if voice.display_name.casefold() == display_name.casefold()
    ]
    if not matches:
        return None
    return min(
        matches,
        key=lambda voice: (
            preferred_description is not None and voice.description != preferred_description,
            voice.voice_id.casefold(),
            voice.voice_id,
        ),
    )


def synthesis_language_for_voice(voice: InworldPublishedVoice) -> str:
    """Convert Inworld's response locale into the BCP-47 form used for synthesis."""
    raw = (voice.language_code or "en-US").replace("_", "-")
    if raw.casefold() == "auto":
        return "en-US"
    language, separator, region = raw.partition("-")
    if not separator:
        return language.casefold()
    return f"{language.casefold()}-{region.upper()}"


async def resolve_character_voice(
    openai_client: AsyncOpenAI,
    inworld_client: httpx.AsyncClient,
    inworld_api_key: str,
    context: CharacterContext,
    *,
    sol_model: str,
    recreate: bool,
) -> tuple[CharacterVoiceResolution, VoiceDesignPlan | None, str | None, bytes | None]:
    """Reuse a named character voice unless explicit regeneration was requested."""
    existing = select_named_inworld_voice(
        await list_inworld_workspace_voices(inworld_client, inworld_api_key),
        context.display_name,
    )
    if existing is not None and not recreate:
        return CharacterVoiceResolution(status="reused", voice=existing), None, None, None

    voice_plan, sol_prompt = await create_voice_design_plan(
        openai_client,
        context,
        model=sol_model,
    )
    design = await design_inworld_voice(
        inworld_client,
        inworld_api_key,
        language_code=voice_plan.language_code,
        design_prompt=voice_plan.profile.render(),
        preview_text=voice_plan.preview_text,
    )
    preview = design.preview_voices[0]
    preview_audio = decode_audio(preview.preview_audio)
    published = await publish_inworld_voice(
        inworld_client,
        inworld_api_key,
        preview,
        display_name=context.display_name,
        description=voice_plan.profile.render(),
        tags=["bgvoice"],
    )
    status: Literal["created", "recreated"] = "recreated" if existing is not None else "created"
    return (
        CharacterVoiceResolution(
            status=status,
            voice=published,
            replaced_voice_id=None if existing is None else existing.voice_id,
        ),
        voice_plan,
        sol_prompt,
        preview_audio,
    )


async def ensure_narrator_voice(
    client: httpx.AsyncClient,
    api_key: str,
) -> tuple[NarratorVoiceResolution, bytes | None]:
    """Reuse the deterministic Narrator voice, or design and publish it once."""
    existing = select_named_inworld_voice(
        await list_inworld_workspace_voices(client, api_key),
        NARRATOR_DISPLAY_NAME,
        preferred_description=NARRATOR_VOICE_DESCRIPTION,
    )
    if existing is not None:
        return NarratorVoiceResolution(status="reused", voice=existing), None

    design = await design_inworld_voice(
        client,
        api_key,
        language_code=NARRATOR_LANGUAGE_CODE,
        design_prompt=NARRATOR_VOICE_DESCRIPTION,
        preview_text=NARRATOR_PREVIEW_TEXT,
    )
    preview = design.preview_voices[0]
    preview_audio = decode_audio(preview.preview_audio)
    published = await publish_inworld_voice(
        client,
        api_key,
        preview,
        display_name=NARRATOR_DISPLAY_NAME,
        description=NARRATOR_VOICE_DESCRIPTION,
        tags=NARRATOR_TAGS,
    )
    return NarratorVoiceResolution(status="created", voice=published), preview_audio


async def synthesize_inworld_line(
    client: httpx.AsyncClient,
    api_key: str,
    voice_id: str,
    directed_text: str,
    language_code: str,
) -> InworldSynthesisResponse:
    """Synthesize the Luna-directed line with Inworld TTS-2."""
    data = await _inworld_post(
        client,
        INWORLD_TTS_URL,
        api_key,
        {
            "text": directed_text,
            "voiceId": voice_id,
            "modelId": INWORLD_TTS_MODEL,
            "audioConfig": {
                "audioEncoding": "LINEAR16",
                "sampleRateHertz": 22050,
                "language": language_code,
            },
            "deliveryMode": "BALANCED",
            "applyTextNormalization": "ON",
            "enhanceGeneration": True,
        },
    )
    return InworldSynthesisResponse.model_validate(data)


def decode_audio(encoded: str) -> bytes:
    try:
        audio = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise RuntimeError("Inworld returned invalid base64 audio") from error
    if not audio:
        raise RuntimeError("Inworld returned empty audio")
    return audio


def audio_suffix(audio: bytes) -> str:
    """Infer a safe extension for the Voice Design preview."""
    if audio.startswith(b"RIFF") and audio[8:12] == b"WAVE":
        return ".wav"
    if audio.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
        return ".mp3"
    if audio.startswith(b"OggS"):
        return ".ogg"
    if audio.startswith(b"fLaC"):
        return ".flac"
    return ".bin"


async def write_bytes(path: Path, content: bytes) -> None:
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, content)


async def write_text(path: Path, content: str) -> None:
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, content, encoding="utf-8")


async def run_pipeline(args: argparse.Namespace) -> Path:
    """Execute the complete asynchronous design, direction, and synthesis workflow."""
    env_path = Path(args.env_file).expanduser().resolve()
    database_path = Path(args.database).expanduser().resolve()
    openai_key, inworld_key = await load_credentials(env_path)
    context, candidates = await load_character_context(
        database_path,
        args.character,
        minimum_characters=args.min_line_characters,
        maximum_characters=args.max_line_characters,
    )
    selected_line = choose_dialogue_line(candidates, args.seed, args.dialogue_id)
    dialogue_history = await load_dialogue_history(database_path, selected_line)

    started = datetime.now(UTC)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else (Path.cwd() / "output" / f"{_slug(args.character)}-{stamp}").resolve()
    )
    if output_dir.exists() and await asyncio.to_thread(lambda: any(output_dir.iterdir())):
        raise FileExistsError(f"output directory is not empty: {output_dir}")
    await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)

    timeout = httpx.Timeout(args.timeout_seconds)
    async with (
        AsyncOpenAI(api_key=openai_key, timeout=args.timeout_seconds) as openai_client,
        httpx.AsyncClient(timeout=timeout) as inworld_client,
    ):
        (
            character_voice_resolution,
            voice_plan,
            sol_prompt,
            preview_audio,
        ) = await resolve_character_voice(
            openai_client,
            inworld_client,
            inworld_key,
            context,
            sol_model=args.sol_model,
            recreate=args.recreate_voice,
        )
        character_voice = character_voice_resolution.voice
        tts_line_plan, luna_prompt = await create_tts_line_plan(
            openai_client,
            selected_line,
            context,
            dialogue_history,
            model=args.luna_model,
        )
        directed_text = tts_line_plan.result.directed_dialogue
        narrator_resolution: NarratorVoiceResolution | None = None
        narrator_preview_audio: bytes | None = None
        synthesis_voice = character_voice
        synthesis_language_code = (
            voice_plan.language_code
            if voice_plan is not None
            else synthesis_language_for_voice(character_voice)
        )
        if tts_line_plan.result.speaker == "narrator":
            narrator_resolution, narrator_preview_audio = await ensure_narrator_voice(
                inworld_client,
                inworld_key,
            )
            synthesis_voice = narrator_resolution.voice
            synthesis_language_code = NARRATOR_LANGUAGE_CODE
        synthesis = await synthesize_inworld_line(
            inworld_client,
            inworld_key,
            synthesis_voice.voice_id,
            directed_text,
            synthesis_language_code,
        )

    final_audio = decode_audio(synthesis.audio_content)
    if not (final_audio.startswith(b"RIFF") and final_audio[8:12] == b"WAVE"):
        raise RuntimeError("Inworld LINEAR16 synthesis did not return a WAV container")
    final_path = output_dir / "dialogue.wav"
    rendered_voice_profile = (
        voice_plan.profile.render() if voice_plan is not None else character_voice.description
    )
    preview_path = (
        output_dir / f"voice-preview{audio_suffix(preview_audio)}"
        if preview_audio is not None
        else None
    )
    profile_path = output_dir / "voice-profile.txt" if rendered_voice_profile else None
    sol_prompt_path = output_dir / "sol-voice-design-prompt.txt" if sol_prompt is not None else None
    luna_prompt_path = output_dir / "luna-tts2-prompt.txt"
    directed_path = output_dir / "directed-dialogue.txt"
    tts_line_plan_path = output_dir / "luna-tts2-plan.json"
    narrator_preview_path = (
        output_dir / f"narrator-voice-preview{audio_suffix(narrator_preview_audio)}"
        if narrator_preview_audio is not None
        else None
    )
    portrait_path = (
        output_dir / "character-portrait.png"
        if context.representative.portrait is not None
        else None
    )
    manifest_path = output_dir / "manifest.json"
    manifest = {
        "created_at": started.isoformat(),
        "character": context.model_dump(mode="json"),
        "models": {
            "voice_design": {
                "id": args.sol_model,
                "reasoning_effort": "medium",
                "used": voice_plan is not None,
            },
            "tts_direction": {"id": args.luna_model, "reasoning_effort": "medium"},
            "synthesis": INWORLD_TTS_MODEL,
        },
        "voice_design": None if voice_plan is None else voice_plan.model_dump(mode="json"),
        "rendered_voice_profile": rendered_voice_profile,
        "inworld_voice": synthesis_voice.model_dump(mode="json"),
        "inworld_character_voice": character_voice.model_dump(mode="json"),
        "character_voice_resolution": character_voice_resolution.model_dump(mode="json"),
        "narrator_voice": (
            None if narrator_resolution is None else narrator_resolution.model_dump(mode="json")
        ),
        "narrator_voice_profile": NARRATOR_VOICE_DESCRIPTION,
        "selected_dialogue": selected_line.model_dump(mode="json"),
        "selected_dialogue_is_narrator_like": is_narrator_like_source(selected_line.text),
        "dialogue_context": [turn.model_dump(mode="json") for turn in dialogue_history],
        "tts_line_plan": tts_line_plan.model_dump(mode="json"),
        "tts_direction": directed_text,
        "inworld_usage": synthesis.usage,
        "artifacts": {
            "voice_preview": None if preview_path is None else preview_path.name,
            "final_audio": final_path.name,
            "voice_profile": None if profile_path is None else profile_path.name,
            "sol_prompt": None if sol_prompt_path is None else sol_prompt_path.name,
            "luna_prompt": luna_prompt_path.name,
            "luna_plan": tts_line_plan_path.name,
            "directed_dialogue": directed_path.name,
            "character_portrait": None if portrait_path is None else portrait_path.name,
            "narrator_voice_preview": (
                None if narrator_preview_path is None else narrator_preview_path.name
            ),
        },
    }
    writes = [
        write_bytes(final_path, final_audio),
        write_text(luna_prompt_path, luna_prompt),
        write_text(
            tts_line_plan_path,
            json.dumps(tts_line_plan.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        ),
        write_text(directed_path, directed_text + "\n"),
        write_text(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"),
    ]
    if preview_path is not None:
        assert preview_audio is not None
        writes.append(write_bytes(preview_path, preview_audio))
    if profile_path is not None:
        assert rendered_voice_profile is not None
        writes.append(write_text(profile_path, rendered_voice_profile + "\n"))
    if sol_prompt_path is not None:
        assert sol_prompt is not None
        writes.append(write_text(sol_prompt_path, sol_prompt))
    if portrait_path is not None:
        portrait = context.representative.portrait
        assert portrait is not None
        writes.append(write_bytes(portrait_path, portrait.png))
    if narrator_preview_path is not None:
        assert narrator_preview_audio is not None
        writes.append(write_bytes(narrator_preview_path, narrator_preview_audio))
    await asyncio.gather(*writes)
    return manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Design an Inworld character voice and synthesize one attributed BGVoice line."
    )
    parser.add_argument("character", nargs="?", default="Imoen")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--database", default="data/bgvoice.lancedb")
    parser.add_argument("--output-dir")
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--dialogue-id",
        help="select one exact eligible dialogue line ID instead of choosing randomly",
    )
    parser.add_argument("--min-line-characters", type=int, default=360)
    parser.add_argument("--max-line-characters", type=int, default=720)
    parser.add_argument("--sol-model", default="gpt-5.6-sol")
    parser.add_argument("--luna-model", default="gpt-5.6-luna")
    parser.add_argument(
        "--recreate-voice",
        action="store_true",
        help=(
            "regenerate the named character voice; Inworld replaces the existing same-name "
            "published voice instead of leaving a copy"
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    args = parser.parse_args()
    if args.min_line_characters < 1:
        parser.error("--min-line-characters must be positive")
    if args.max_line_characters < args.min_line_characters:
        parser.error("--max-line-characters must be at least the minimum")
    if args.max_line_characters > 2000:
        parser.error("--max-line-characters cannot exceed Inworld's 2,000-character limit")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    return args


def main() -> None:
    manifest_path = asyncio.run(run_pipeline(parse_args()))
    print(f"Completed voice test. Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
