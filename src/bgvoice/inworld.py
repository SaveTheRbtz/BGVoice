"""Typed asynchronous access to the Inworld voice and batch TTS APIs."""

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

from bgvoice.model_types import StrictModel

INWORLD_TTS_MODEL = "inworld-tts-2"
INWORLD_AUDIO_ENCODING = "WAV"
INWORLD_SAMPLE_RATE_HERTZ = 22_050
INWORLD_BATCH_CHARACTER_LIMIT = 10_000
INWORLD_BATCH_ITEM_LIMIT = 10_000

_API_ROOT = "https://api.inworld.ai"
_DESIGN_VOICE_URL = f"{_API_ROOT}/voices/v1/voices:design"
_BATCH_TTS_URL = f"{_API_ROOT}/tts/v1/voice:synthesizeBatch"


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        error.add_note(response.text)
        raise


class VoiceDesignRequest(StrictModel):
    """Input accepted by Inworld Voice Design."""

    language_code: Annotated[str, Field(min_length=2)]
    design_prompt: Annotated[str, Field(min_length=30, max_length=1000)]
    preview_text: Annotated[str, Field(min_length=1, max_length=400)]


class BatchSynthesisItem(StrictModel):
    """One caller-addressable line in an Inworld batch TTS job."""

    custom_id: Annotated[str, Field(min_length=1, max_length=63)]
    text: Annotated[str, Field(min_length=1, max_length=100_000)]
    voice_id: Annotated[str, Field(min_length=1)]
    language_code: Annotated[str, Field(min_length=2)]


class _ProviderResponse(BaseModel):
    """Accept additive provider fields while validating everything we consume."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class DraftVoice(_ProviderResponse):
    voice_id: str = Field(alias="voiceId", min_length=1)
    preview_text: str = Field(alias="previewText")
    preview_audio: str = Field(alias="previewAudio", min_length=1)


class VoiceDesignResponse(_ProviderResponse):
    language_code: str = Field(alias="langCode", min_length=1)
    preview_voices: Annotated[list[DraftVoice], Field(min_length=1)] = Field(alias="previewVoices")


class PublishedVoice(_ProviderResponse):
    name: str = Field(min_length=1)
    voice_id: str = Field(alias="voiceId", min_length=1)
    display_name: str = Field(alias="displayName", min_length=1)
    description: str = ""
    language_code: str | None = Field(default=None, alias="languageCode")
    legacy_language_code: str | None = Field(default=None, alias="langCode")
    tags: list[str] = Field(default_factory=list)
    source: str | None = None


class VoiceListResponse(_ProviderResponse):
    voices: list[PublishedVoice]
    next_page_token: str = Field(default="", alias="nextPageToken")


class OperationError(_ProviderResponse):
    code: int
    message: str = Field(min_length=1)


class BatchOperationResponse(_ProviderResponse):
    results_uri: str = Field(alias="resultsUri", min_length=1)
    expire_time: datetime = Field(alias="expireTime")


class BatchOperation(_ProviderResponse):
    name: str = Field(min_length=1)
    done: bool = False
    response: BatchOperationResponse | None = None
    error: OperationError | None = None


class BatchItemError(_ProviderResponse):
    code: str | int | None = None
    message: str = Field(min_length=1)


class BatchResult(_ProviderResponse):
    custom_id: str = Field(alias="customId", min_length=1)
    audio_uri: str | None = Field(default=None, alias="audioUri")
    error: BatchItemError | None = None


class BatchResults(_ProviderResponse):
    results: list[BatchResult]
    failed_items: int = Field(default=0, alias="failedItems", ge=0)


def pack_synthesis_items(
    items: Sequence[BatchSynthesisItem],
) -> list[list[BatchSynthesisItem]]:
    """Pack ordered items into On-Demand-compatible batches of at most 10k characters."""
    batches: list[list[BatchSynthesisItem]] = []
    batch: list[BatchSynthesisItem] = []
    characters = 0

    for item in items:
        item_characters = len(item.text)
        assert item_characters <= INWORLD_BATCH_CHARACTER_LIMIT, (
            f"batch item {item.custom_id!r} exceeds the 10,000-character batch limit"
        )
        if batch and (
            characters + item_characters > INWORLD_BATCH_CHARACTER_LIMIT
            or len(batch) == INWORLD_BATCH_ITEM_LIMIT
        ):
            batches.append(batch)
            batch = []
            characters = 0
        batch.append(item)
        characters += item_characters

    if batch:
        batches.append(batch)
    return batches


class InworldClient:
    """Small async boundary for the Inworld operations used by the pipeline."""

    def __init__(self, http: httpx.AsyncClient, api_key: str) -> None:
        assert api_key, "Inworld API key is required"
        self._http = http
        self._headers = {"Authorization": f"Basic {api_key}"}

    async def design_voice(self, request: VoiceDesignRequest) -> VoiceDesignResponse:
        response = await self._http.post(
            _DESIGN_VOICE_URL,
            headers=self._headers,
            json={
                "languageCode": request.language_code,
                "designPrompt": request.design_prompt,
                "previewText": request.preview_text,
                "voiceDesignConfig": {"numberOfSamples": 1},
            },
        )
        _raise_for_status(response)
        return VoiceDesignResponse.model_validate_json(response.content)

    async def list_voices(self) -> list[PublishedVoice]:
        """List every published voice owned by BGVoice, across provider pages."""
        voices: list[PublishedVoice] = []
        page_token = ""
        while True:
            response = await self._http.get(
                f"{_API_ROOT}/voices/v1/voices",
                headers=self._headers,
                params={
                    "filter": 'source = "IVC" AND tags:"bgvoice"',
                    "pageSize": 2_000,
                    "pageToken": page_token,
                },
            )
            _raise_for_status(response)
            page = VoiceListResponse.model_validate_json(response.content)
            voices.extend(page.voices)
            if not page.next_page_token:
                return voices
            page_token = page.next_page_token

    async def publish_voice(
        self,
        draft_voice_id: str,
        *,
        display_name: str,
        description: str,
        tags: Sequence[str] = (),
    ) -> PublishedVoice:
        assert draft_voice_id, "draft voice ID is required"
        response = await self._http.post(
            f"{_API_ROOT}/voices/v1/voices/{quote(draft_voice_id, safe='')}:publish",
            headers=self._headers,
            json={
                "displayName": display_name,
                "description": description,
                "tags": list(tags),
            },
        )
        _raise_for_status(response)
        return PublishedVoice.model_validate_json(response.content)

    async def delete_voice(self, voice_id: str) -> None:
        assert voice_id, "voice ID is required"
        response = await self._http.delete(
            f"{_API_ROOT}/voices/v1/voices/{quote(voice_id, safe='')}",
            headers=self._headers,
        )
        _raise_for_status(response)

    async def submit_batch(self, items: Sequence[BatchSynthesisItem]) -> BatchOperation:
        assert items, "a synthesis batch cannot be empty"
        assert len(items) <= INWORLD_BATCH_ITEM_LIMIT, "a synthesis batch has too many items"
        assert sum(len(item.text) for item in items) <= INWORLD_BATCH_CHARACTER_LIMIT, (
            "a synthesis batch exceeds 10,000 characters"
        )
        assert len({item.custom_id for item in items}) == len(items), (
            "custom IDs must be unique within a synthesis batch"
        )
        response = await self._http.post(
            _BATCH_TTS_URL,
            headers=self._headers,
            json={
                "items": [
                    {
                        "customId": item.custom_id,
                        "request": {
                            "text": item.text,
                            "voiceId": item.voice_id,
                            "modelId": INWORLD_TTS_MODEL,
                            "audioConfig": {
                                "audioEncoding": INWORLD_AUDIO_ENCODING,
                                "sampleRateHertz": INWORLD_SAMPLE_RATE_HERTZ,
                            },
                            "language": item.language_code,
                            "deliveryMode": "BALANCED",
                            "applyTextNormalization": "ON",
                            "enhanceGeneration": True,
                        },
                    }
                    for item in items
                ]
            },
        )
        _raise_for_status(response)
        return BatchOperation.model_validate_json(response.content)

    async def get_operation(self, name: str) -> BatchOperation:
        assert name, "operation name is required"
        response = await self._http.get(
            f"{_API_ROOT}/lro/v1alpha/{name}",
            headers=self._headers,
        )
        _raise_for_status(response)
        return BatchOperation.model_validate_json(response.content)

    async def poll_operation(
        self,
        name: str,
        *,
        interval_seconds: float = 5.0,
    ) -> BatchOperation:
        """Poll an existing operation until Inworld reports a terminal result."""
        while True:
            operation = await self.get_operation(name)
            if operation.done:
                return operation
            await asyncio.sleep(interval_seconds)

    async def download_results(self, results_uri: str) -> BatchResults:
        """Download a signed batch manifest without attaching Inworld credentials."""
        response = await self._http.get(results_uri)
        _raise_for_status(response)
        return BatchResults.model_validate_json(response.content)

    async def download_audio(self, audio_uri: str) -> bytes:
        """Download one signed audio object without attaching Inworld credentials."""
        response = await self._http.get(audio_uri)
        _raise_for_status(response)
        return bytes(response.content)
