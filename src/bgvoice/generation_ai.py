"""Typed OpenAI boundary for voice research and dialogue direction."""

import base64
import logging
import re
from typing import Annotated, Literal, Self, cast
from urllib.parse import urlsplit

from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam
from openai.types.responses.parsed_response import ParsedResponse
from openai.types.responses.response_usage import ResponseUsage
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

logger = logging.getLogger(__name__)

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
_INSTRUCTION_TAG = re.compile(r"\[[^\]\r\n]+\]")
_NONVERBAL_TAGS = ("[laugh]", "[sigh]", "[clear throat]", "[breathe]", "[cough]", "[yawn]")
_AUDIO_QUALITY_SUFFIX = "Perfect broadcast quality audio."
_AUDIO_QUALITY_TAIL = re.compile(
    r"\s*perfect broadcast quality audio\.?\s*$",
    re.IGNORECASE,
)
_VOICE_ATTRIBUTE_MAX_LENGTH = 70
_TEXTURE_MAX_LENGTH = 120
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


def _log_usage(
    usage: ResponseUsage | None,
    *,
    operation: str,
    model: str,
    response_id: str,
    attempt: int,
    items: int,
) -> None:
    if usage is None:
        return
    reasoning = usage.output_tokens_details.reasoning_tokens
    logger.info(
        "openai_usage operation=%s model=%s response_id=%s attempt=%d items=%d "
        "input_tokens=%d cached_input_tokens=%d cache_write_tokens=%d output_tokens=%d "
        "reasoning_tokens=%d visible_output_tokens=%d total_tokens=%d",
        operation,
        model,
        response_id,
        attempt,
        items,
        usage.input_tokens,
        usage.input_tokens_details.cached_tokens,
        usage.input_tokens_details.cache_write_tokens,
        usage.output_tokens,
        reasoning,
        usage.output_tokens - reasoning,
        usage.total_tokens,
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
    if len(value) <= maximum_length:
        return value
    shortened = value[: maximum_length + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return shortened or value[:maximum_length]


class _StructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VoiceProfile(_StructuredOutput):
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
        if not isinstance(value, str):
            return value
        return _shorten_at_word_boundary(" ".join(value.split()), _VOICE_ATTRIBUTE_MAX_LENGTH)

    @field_validator("texture", mode="before")
    @classmethod
    def add_audio_quality_suffix(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        base = _AUDIO_QUALITY_TAIL.sub("", " ".join(value.split())).rstrip(" ,;:.")
        maximum_base_length = _TEXTURE_MAX_LENGTH - len(_AUDIO_QUALITY_SUFFIX) - 2
        base = _shorten_at_word_boundary(base, maximum_base_length).rstrip(" ,;:.")
        return f"{base}. {_AUDIO_QUALITY_SUFFIX}" if base else _AUDIO_QUALITY_SUFFIX

    @field_validator("*")
    @classmethod
    def clean_attribute(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if ":" in cleaned or "\n" in cleaned or "\r" in cleaned:
            raise ValueError("voice attributes must be single values, not nested fields")
        if not cleaned.isascii() or any(not 32 <= ord(character) <= 126 for character in cleaned):
            raise ValueError("voice attributes must contain only visible printable ASCII")
        return cleaned

    @model_validator(mode="after")
    def reject_fictional_dialect(self) -> Self:
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
        values = self.model_dump()
        return "\n".join(f"{name}: {values[name]}" for name in _PROFILE_FIELDS)


class VoiceDesignPlan(_StructuredOutput):
    """Web-researched, API-compatible voice design result."""

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


class CharacterAbilityScores(_StructuredOutput):
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


class VoiceDesignSource(_StructuredOutput):
    """Installation evidence supplied to voice research."""

    display_name: str = Field(min_length=1)
    metadata: str = Field(min_length=1)
    biography: str | None = None
    ability_scores: CharacterAbilityScores
    portrait_png: bytes | None = Field(default=None, exclude=True, repr=False)


def build_voice_design_prompt(context: VoiceDesignSource) -> str:
    """Create the tuned character-research and voice-direction prompt."""
    biography = (
        f"\n\n{context.display_name} biography:\n{context.biography}"
        if context.biography is not None
        else f"\n\n{context.display_name} biography: unavailable."
    )
    portrait = (
        f"A local game portrait of {context.display_name} is attached."
        if context.portrait_png is not None
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
- Ability scores: {context.ability_scores.render()}
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
    context: VoiceDesignSource,
    prompt: str,
) -> list[dict[str, object]]:
    content: list[dict[str, object]] = [{"type": "input_text", "text": prompt}]
    if context.portrait_png is not None:
        encoded = base64.b64encode(context.portrait_png).decode("ascii")
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{encoded}",
                "detail": "high",
            }
        )
    return content


def _response_used_web_search(response: ParsedResponse[VoiceDesignPlan]) -> bool:
    return any(str(getattr(item, "type", "")).startswith("web_search") for item in response.output)


async def create_voice_design_plan(
    client: AsyncOpenAI,
    context: VoiceDesignSource,
    *,
    model: str,
) -> VoiceDesignPlan:
    """Ask the research model for a web-grounded, provider-ready voice profile."""
    prompt = build_voice_design_prompt(context)
    errors: list[str] = []
    for attempt in range(1, 4):
        retry_note = ""
        if errors:
            retry_note = (
                "\nThe previous result failed local compatibility validation: "
                + errors[-1]
                + " Correct that issue while following every original requirement."
            )
        try:
            response = await client.responses.parse(
                model=model,
                reasoning={"effort": "medium"},
                tools=[{"type": "web_search"}],
                tool_choice="required",
                max_tool_calls=4,
                include=["web_search_call.action.sources"],
                store=False,
                input=cast(
                    ResponseInputParam,
                    [
                        {
                            "role": "developer",
                            "content": (
                                "You are an expert casting director and voice designer. "
                                "Research carefully, distinguish fact from inference, and emit "
                                "only the supplied Structured Output."
                            ),
                        },
                        {
                            "role": "user",
                            "content": build_voice_design_content(context, prompt + retry_note),
                        },
                    ],
                ),
                text_format=VoiceDesignPlan,
            )
            _log_usage(
                response.usage,
                operation="voice_design",
                model=model,
                response_id=response.id,
                attempt=attempt,
                items=1,
            )
            plan = response.output_parsed
            if plan is None:
                raise RuntimeError(f"{model} returned no parsed voice design")
            if not _response_used_web_search(response):
                raise RuntimeError(f"{model} did not use the required web search tool")
            return plan
        except (ValidationError, ValueError, RuntimeError) as error:
            errors.append(str(error)[:500])
    raise RuntimeError(
        f"{model} could not produce an Inworld-compatible voice design: {errors[-1]}"
    )


class NarratorDirectedDialogue(_StructuredOutput):
    """Scene narration routed to the shared narrator voice."""

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


class CharacterDirectedDialogue(_StructuredOutput):
    """Dialogue routed to the named character voice."""

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


# Structured Outputs supports nested ``anyOf`` but rejects the ``oneOf`` emitted by Pydantic's
# discriminator option. The required Literal speaker fields still make these branches unambiguous.
DirectedDialogue = Annotated[
    NarratorDirectedDialogue | CharacterDirectedDialogue,
    Field(
        description=(
            "Exactly one speaker-routed TTS direction. Choose the variant from the intended "
            "speaker of the source line, not merely from the presence of punctuation."
        ),
    ),
]


class DirectionPlan(_StructuredOutput):
    """One strongly discriminated dialogue direction."""

    result: DirectedDialogue


class DirectionSource(_StructuredOutput):
    """One source line with its speaker evidence and unspoken context."""

    display_name: str = Field(min_length=1)
    metadata: str = Field(min_length=1)
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    dialogue_history: Annotated[str | None, Field(max_length=1200)] = None


def build_direction_prompt(source: DirectionSource) -> str:
    """Create the tuned prompt for one dialogue line."""
    history = source.dialogue_history or ""
    return f"""Route and direct the following attributed {source.display_name} dialogue from
Baldur's Gate. Each stored NPC line may be either actual character speech or authorial scene
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

First decide who is intended to speak each target line:

- Choose the narrator result when the line is primarily authorial prose describing a scene,
  action, passage of time, dream, or visual event rather than words spoken by
  {source.display_name}. Fully enclosing asterisks or parentheses are strong evidence of
  narration, but punctuation alone is not decisive. Strip those source-only wrappers and retain
  the narrative prose as spoken narrator text.
- Choose the character result when direct speech by {source.display_name} is the main content.
  A brief stage direction such as *sighs* or *whispering* before actual speech does not make the
  line narration.
- Use exactly one speaker for each result. Never include the speaker choice in the spoken text,
  and never copy the unspoken scene context into it.

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
it to invent runtime-dependent details. Return exactly one speaker-routed, rewritten,
TTS-directed result.

Character metadata:
{source.metadata}

Read <context_not_for_tts> only to understand delivery and meaning. Rewrite and direct only
<tts_source>. directed_dialogue must remain semantically equivalent to <tts_source>, except for
placeholder replacement and removal or conversion of embedded stage directions.

<requested_item>
<context_not_for_tts>
{history}
</context_not_for_tts>

<tts_source>
{source.text}
</tts_source>
</requested_item>"""


def validate_directed_dialogue(
    source: DirectionSource,
    result: NarratorDirectedDialogue | CharacterDirectedDialogue,
) -> None:
    """Reject results that retained source-only syntax or copied scene context."""
    directed = result.directed_dialogue
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
        result.speaker == "narrator"
        and stripped_directed.startswith("(")
        and stripped_directed.endswith(")")
    ):
        raise ValueError("narrator dialogue still has source-only enclosing parentheses")

    normalized_original = " ".join(source.text.split()).casefold()
    normalized_directed = " ".join(_INSTRUCTION_TAG.sub("", directed).split()).casefold()
    for value in _history_evidence(source.dialogue_history):
        normalized_context = " ".join(value.split()).casefold()
        if (
            len(normalized_context) >= 30
            and normalized_context not in normalized_original
            and normalized_context in normalized_directed
        ):
            raise ValueError("directed dialogue repeats unspoken scene context")


def _history_evidence(history: str | None) -> list[str]:
    if not history:
        return []
    prefixes = ("Previous NPC/scene line:", "Player response:")
    return [
        line.removeprefix(prefix).strip()
        for line in history.splitlines()
        for prefix in prefixes
        if line.startswith(prefix) and line.removeprefix(prefix).strip()
    ]


def tts_speakable_text(text: str) -> str:
    """Render silent delivery-only results as a neutral supported non-verbal."""
    folded = text.casefold()
    if any(tag in folded for tag in _NONVERBAL_TAGS):
        return text
    without_instructions = _INSTRUCTION_TAG.sub("", text)
    return text if any(character.isalnum() for character in without_instructions) else "[breathe]"


async def create_direction(
    client: AsyncOpenAI,
    source: DirectionSource,
    *,
    model: str,
) -> DirectionPlan:
    """Route and direct one line without granting the dialogue model any tools."""
    prompt = build_direction_prompt(source)
    errors: list[str] = []
    for attempt in range(1, 4):
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
                input=cast(
                    ResponseInputParam,
                    [
                        {
                            "role": "developer",
                            "content": (
                                "You direct expressive game dialogue for Inworld TTS-2. "
                                "Choose the intended narrator or character speaker, then obey the "
                                "placeholder and stage-direction rewriting rules exactly. Only "
                                "the text inside <tts_source> may be transformed "
                                "or spoken. <context_not_for_tts> is read-only evidence. Never quote, "
                                "paraphrase, summarize, continue, or otherwise include it in "
                                "directed_dialogue. Do not replace the target with a line that seems "
                                "more contextually appropriate. Return only the supplied Structured "
                                "Output."
                            ),
                        },
                        {"role": "user", "content": prompt + retry_note},
                    ],
                ),
                text_format=DirectionPlan,
            )
            _log_usage(
                response.usage,
                operation="dialogue_direction",
                model=model,
                response_id=response.id,
                attempt=attempt,
                items=1,
            )
            plan = response.output_parsed
            if plan is None:
                raise RuntimeError(f"{model} returned no parsed direction")
            validate_directed_dialogue(source, plan.result)
            return plan
        except (ValidationError, ValueError, RuntimeError) as error:
            errors.append(str(error)[:500])
    raise RuntimeError(f"{model} could not route and direct the requested line: {errors[-1]}")
