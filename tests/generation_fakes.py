"""Typed boundary fakes shared by generation behavior tests."""

import json
import wave
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from typing import Any, ClassVar, Self, cast

import httpx

import bgvoice.generation as generation_module
from bgvoice.generation_ai import (
    CharacterDirectedDialogue,
    DirectionPlan,
    NarratorDirectedDialogue,
    VoiceDesignPlan,
    VoiceProfile,
)
from bgvoice.inworld import (
    BatchItemError,
    BatchOperation,
    BatchOperationResponse,
    BatchResult,
    BatchResults,
    BatchSynthesisItem,
    OperationError,
    PublishedVoice,
)


class FakeHttp:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeResponses:
    calls: ClassVar[list[dict[str, object]]] = []

    async def parse(self, **arguments: object) -> object:
        self.calls.append(arguments)
        usage = SimpleNamespace(
            input_tokens=120,
            input_tokens_details=SimpleNamespace(cached_tokens=80, cache_write_tokens=0),
            output_tokens=40,
            output_tokens_details=SimpleNamespace(reasoning_tokens=30),
            total_tokens=160,
        )
        if arguments["text_format"] is VoiceDesignPlan:
            return SimpleNamespace(
                id="voice-design-response",
                usage=usage,
                output_parsed=VoiceDesignPlan(
                    language_code="en-GB",
                    profile=VoiceProfile(
                        dialect="English with a subtle northern English accent",
                        gender="female",
                        age="young adult",
                        emotion="earnest and hopeful",
                        tone="warm and conversational",
                        pitch="medium-high",
                        volume="moderate",
                        speed="quick but articulate",
                        clarity="clear",
                        fluency="fluent",
                        personality="compassionate and resilient",
                        texture="bright and lightly breathy",
                    ),
                    preview_text="We travel together, and we shall face whatever waits ahead.",
                    research_summary="Game evidence agrees with published character references.",
                    source_urls=["https://example.com/aerie"],
                ),
                output=[SimpleNamespace(type="web_search_call")],
            )

        messages = cast(list[dict[str, object]], arguments["input"])
        content = cast(str, messages[1]["content"])
        return SimpleNamespace(
            id="direction-response",
            usage=usage,
            output_parsed=DirectionPlan(
                result=(
                    NarratorDirectedDialogue(
                        speaker="narrator",
                        directed_dialogue="[narrate calmly] The road grows quiet as night falls.",
                    )
                    if "A quest for <DAYANDMONTH>." in content
                    else CharacterDirectedDialogue(
                        speaker="character",
                        directed_dialogue="[warmly] Hello.",
                    )
                )
            ),
        )


class FakeOpenAI:
    def __init__(self, *, api_key: str) -> None:
        assert api_key == "openai-test"
        self.responses = FakeResponses()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class VoiceProviderFake:
    def __init__(self, existing_profile_id: str | None = None) -> None:
        self.designs = 0
        self.publishes = 0
        self.updates = 0
        self.voices = (
            []
            if existing_profile_id is None
            else [
                PublishedVoice(
                    name=f"workspaces/test/voices/{existing_profile_id}-existing",
                    voiceId=f"{existing_profile_id}-existing",
                    displayName=existing_profile_id.title(),
                    description="An existing carefully designed voice.",
                    langCode="EN_GB",
                    tags=[
                        "bgvoice",
                        generation_module.voice_profile_tag(existing_profile_id),
                    ],
                    source="IVC",
                )
            ]
        )

    async def list_voices(self) -> list[PublishedVoice]:
        return self.voices

    async def design_voice(self, _request: object) -> object:
        self.designs += 1
        return SimpleNamespace(preview_voices=[SimpleNamespace(voice_id="draft-default")])

    async def publish_voice(
        self,
        _draft_voice_id: str,
        *,
        display_name: str,
        description: str,
        tags: tuple[str, ...],
    ) -> PublishedVoice:
        self.publishes += 1
        return PublishedVoice(
            name="workspaces/test/voices/generic-female-elf",
            voiceId="generic-female-elf",
            displayName=display_name,
            description=description,
            langCode="EN_GB",
            tags=list(tags),
            source="IVC",
        )

    async def update_voice(
        self,
        voice_id: str,
        *,
        display_name: str,
        description: str,
        tags: tuple[str, ...],
        gender: str | None = None,
    ) -> PublishedVoice:
        self.updates += 1
        return PublishedVoice(
            name=f"workspaces/test/voices/{voice_id}",
            voiceId=voice_id,
            displayName=display_name,
            description=description,
            langCode="EN_GB",
            tags=list(tags),
            source="IVC",
        )


class FailedBatchProvider:
    async def poll_operation(self, name: str) -> BatchOperation:
        return BatchOperation(
            name=name,
            done=True,
            error=OperationError(code=13, message="provider synthesis failed"),
        )


class MixedBatchProvider:
    def __init__(self, custom_ids: list[str]) -> None:
        self.custom_ids = custom_ids
        self.recovered = False
        self.downloads: list[str] = []

    async def poll_operation(self, name: str) -> BatchOperation:
        return BatchOperation(
            name=name,
            done=True,
            response=BatchOperationResponse(
                results_uri="https://signed.example/results",
                expire_time=datetime(2026, 9, 3, tzinfo=UTC),
            ),
        )

    async def download_results(self, _results_uri: str) -> BatchResults:
        if self.recovered:
            return BatchResults(
                results=[
                    BatchResult(custom_id=custom_id, audio_uri=f"audio:{index}")
                    for index, custom_id in enumerate(self.custom_ids)
                ]
            )
        return BatchResults(
            results=[
                BatchResult(
                    custom_id=self.custom_ids[0],
                    error=BatchItemError(code="bad-input", message="text was rejected"),
                ),
                BatchResult(custom_id=self.custom_ids[1]),
                BatchResult(custom_id=self.custom_ids[2], audio_uri="audio:broken"),
                BatchResult(custom_id=self.custom_ids[3], audio_uri="audio:good"),
            ],
            failed_items=3,
        )

    async def download_audio(self, audio_uri: str) -> bytes:
        self.downloads.append(audio_uri)
        if not self.recovered and audio_uri == "audio:broken":
            raise RuntimeError("signed audio download failed")
        return audio_uri.encode()


class RecordingBatchProvider:
    def __init__(self) -> None:
        self.submitted: list[BatchSynthesisItem] = []

    async def submit_batch(self, items: list[BatchSynthesisItem]) -> BatchOperation:
        self.submitted.extend(items)
        return BatchOperation(name="workspaces/test/ttsBatchJobs/new/operations/op")


class InworldService:
    """Stateful HTTP boundary fake for the full generation integration test."""

    def __init__(self) -> None:
        audio = BytesIO()
        with wave.open(audio, "wb") as pcm:
            pcm.setnchannels(1)
            pcm.setsampwidth(2)
            pcm.setframerate(22_050)
            pcm.writeframes(b"\0\0" * 2_205)

        self.provider_audio = audio.getvalue()
        self.drafts = 0
        self.batch_count = 0
        self.voice_list_requests = 0
        self.operations: dict[str, list[str]] = {}
        self.published: dict[str, dict[str, object]] = {}
        self.published_names: list[str] = []
        self.deleted_voice_ids: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/voices/v1/voices" and request.method == "GET":
            self.voice_list_requests += 1
            return httpx.Response(200, json={"voices": list(self.published.values())})
        if path == "/voices/v1/voices:design":
            self.drafts += 1
            return httpx.Response(
                200,
                json={
                    "langCode": "EN_GB",
                    "previewVoices": [
                        {
                            "voiceId": f"draft-{self.drafts}",
                            "previewText": "Ready.",
                            "previewAudio": "UklGRg==",
                        }
                    ],
                },
            )
        if path.endswith(":publish"):
            body = cast(dict[str, Any], json.loads(request.content))
            display_name = cast(str, body["displayName"])
            voice_id = f"voice-{display_name.casefold().replace(' ', '-')}-{self.drafts}"
            voice = {
                "name": f"workspaces/test/voices/{voice_id}",
                "voiceId": voice_id,
                "displayName": display_name,
                "description": body["description"],
                "langCode": "EN_GB",
                "tags": body["tags"],
                "source": "IVC",
            }
            self.published[voice_id] = voice
            self.published_names.append(display_name)
            return httpx.Response(200, json=voice)
        if path.startswith("/voices/v1/voices/") and request.method == "PATCH":
            voice_id = path.rsplit("/", 1)[1]
            body = cast(dict[str, Any], json.loads(request.content))
            voice = self.published[voice_id]
            voice.update(
                displayName=body["displayName"],
                description=body["description"],
                tags=body["tags"],
            )
            return httpx.Response(200, json=voice)
        if path.startswith("/voices/v1/voices/") and request.method == "DELETE":
            voice_id = path.rsplit("/", 1)[1]
            assert voice_id in self.published
            del self.published[voice_id]
            self.deleted_voice_ids.append(voice_id)
            return httpx.Response(200)
        if path == "/tts/v1/voice:synthesizeBatch":
            self.batch_count += 1
            body = cast(dict[str, Any], json.loads(request.content))
            custom_ids = [cast(str, item["customId"]) for item in body["items"]]
            name = f"workspaces/test/ttsBatchJobs/{self.batch_count}/operations/op"
            self.operations[name] = custom_ids
            return httpx.Response(200, json={"name": name})
        if path.startswith("/lro/v1alpha/"):
            name = path.removeprefix("/lro/v1alpha/")
            assert name in self.operations
            return httpx.Response(
                200,
                json={
                    "name": name,
                    "done": True,
                    "response": {
                        "resultsUri": f"https://signed.example/results/{name.split('/')[3]}",
                        "expireTime": "2026-09-03T12:00:00Z",
                    },
                },
            )
        if request.url.host == "signed.example" and path.startswith("/results/"):
            batch_number = path.rsplit("/", 1)[1]
            name = f"workspaces/test/ttsBatchJobs/{batch_number}/operations/op"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "customId": custom_id,
                            "audioUri": f"https://signed.example/audio/{custom_id}.wav",
                        }
                        for custom_id in self.operations[name]
                    ]
                },
            )
        if request.url.host == "signed.example" and path.startswith("/audio/"):
            return httpx.Response(200, content=self.provider_audio)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")
