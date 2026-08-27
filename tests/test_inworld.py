"""The typed HTTP boundary for Inworld voice design and batch synthesis."""

import json
from collections.abc import Sequence

import httpx
import pytest
from pydantic import ValidationError

from bgvoice.inworld import (
    BatchSynthesisItem,
    InworldClient,
    VoiceDesignRequest,
    pack_synthesis_items,
)


def _item(custom_id: str, characters: int) -> BatchSynthesisItem:
    return BatchSynthesisItem(
        custom_id=custom_id,
        text="x" * characters,
        voice_id="workspace__imoen",
        language_code="en-GB",
    )


def test_batch_packing_preserves_order_and_respects_the_on_demand_limit() -> None:
    items = [_item("a", 6_000), _item("b", 4_000), _item("c", 1)]

    assert [[item.custom_id for item in batch] for batch in pack_synthesis_items(items)] == [
        ["a", "b"],
        ["c"],
    ]
    assert pack_synthesis_items([]) == []

    with pytest.raises(AssertionError, match="exceeds"):
        pack_synthesis_items([_item("large", 10_001)])


@pytest.mark.parametrize("length", [29, 251])
def test_voice_design_rejects_provider_invalid_prompt_lengths(length: int) -> None:
    with pytest.raises(ValidationError):
        VoiceDesignRequest(
            language_code="en-GB",
            design_prompt="x" * length,
            preview_text="Hello there.",
        )


@pytest.mark.anyio
async def test_voice_design_publish_and_batch_download_flow_is_typed() -> None:
    requests: list[httpx.Request] = []
    operation_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal operation_reads
        requests.append(request)
        path = request.url.path

        if path == "/voices/v1/voices:design":
            return httpx.Response(
                200,
                json={
                    "langCode": "EN_GB",
                    "previewVoices": [
                        {
                            "voiceId": "workspace__draft",
                            "previewText": "Ready when you are.",
                            "previewAudio": "UklGRg==",
                            "futureField": True,
                        }
                    ],
                },
            )
        if path == "/voices/v1/voices" and request.method == "GET":
            if request.url.params["pageToken"]:
                return httpx.Response(200, json={"voices": []})
            return httpx.Response(
                200,
                json={
                    "voices": [
                        {
                            "name": "workspaces/workspace/voices/imoen",
                            "voiceId": "workspace__imoen",
                            "langCode": "EN_GB",
                            "displayName": "Imoen",
                            "description": "A bright, warm existing voice for Imoen.",
                            "tags": ["bgvoice"],
                            "source": "IVC",
                        }
                    ],
                    "nextPageToken": "next-page",
                },
            )
        if path == "/voices/v1/voices/workspace__draft:publish":
            return httpx.Response(
                200,
                json={
                    "name": "workspaces/workspace/voices/imoen",
                    "voiceId": "workspace__imoen",
                    "languageCode": "en-GB",
                    "langCode": "EN_GB",
                    "displayName": "Imoen",
                    "description": "Bright and warm.",
                    "tags": ["bgvoice"],
                    "source": "IVC",
                },
            )
        if path == "/voices/v1/voices/workspace__unused" and request.method == "DELETE":
            return httpx.Response(200, json={})
        if path == "/tts/v1/voice:synthesizeBatch":
            return httpx.Response(
                200,
                json={
                    "name": "workspaces/workspace/ttsBatchJobs/job/operations/op",
                    "metadata": None,
                    "done": False,
                },
            )
        if path.startswith("/lro/v1alpha/workspaces/"):
            operation_reads += 1
            if operation_reads == 1:
                return httpx.Response(
                    200,
                    json={
                        "name": "workspaces/workspace/ttsBatchJobs/job/operations/op",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "name": "workspaces/workspace/ttsBatchJobs/job/operations/op",
                    "done": True,
                    "response": {
                        "@type": "type.googleapis.com/inworld.SynthesizeSpeechBatchResponse",
                        "resultsUri": "https://signed.example/results.json",
                        "expireTime": "2026-09-03T12:00:00Z",
                    },
                },
            )
        if request.url == httpx.URL("https://signed.example/results.json"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "customId": "line-a",
                            "audioUri": "https://signed.example/line-a.mp3",
                        },
                        {
                            "customId": "line-b",
                            "error": {"code": "UNAVAILABLE", "message": "try later"},
                        },
                    ],
                    "failedItems": 1,
                },
            )
        if request.url == httpx.URL("https://signed.example/line-a.mp3"):
            return httpx.Response(200, content=b"ID3audio")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = InworldClient(http, "secret")
        design_request = VoiceDesignRequest(
            language_code="en-GB",
            design_prompt="A bright, warm, playful young adventurer voice.",
            preview_text="Heya! It's me, Imoen. Ready when you are.",
        )
        design = await client.design_voice(design_request)
        existing = await client.list_voices()
        voice = await client.publish_voice(
            design.preview_voices[0].voice_id,
            display_name="Imoen",
            description="Bright and warm.",
            tags=("bgvoice",),
        )
        await client.delete_voice("workspace__unused")
        items: Sequence[BatchSynthesisItem] = [
            BatchSynthesisItem(
                custom_id="line-a",
                text="Heya!",
                voice_id=voice.voice_id,
                language_code="en-GB",
            ),
            BatchSynthesisItem(
                custom_id="line-b",
                text="What's this, then?",
                voice_id=voice.voice_id,
                language_code="en-GB",
            ),
        ]
        submitted = await client.submit_batch(items)
        completed = await client.poll_operation(submitted.name, interval_seconds=0)
        assert completed.response is not None
        results = await client.download_results(completed.response.results_uri)
        assert results.results[0].audio_uri is not None
        audio = await client.download_audio(results.results[0].audio_uri)

    assert design.language_code == "EN_GB"
    assert existing[0].source == "IVC"
    assert voice.language_code == "en-GB"
    assert audio == b"ID3audio"
    assert results.failed_items == 1
    assert results.results[1].error is not None
    assert results.results[1].error.message == "try later"

    bodies = {
        request.url.path: json.loads(request.content)
        for request in requests
        if request.method == "POST"
    }
    assert bodies["/voices/v1/voices:design"] == {
        "languageCode": "en-GB",
        "designPrompt": "A bright, warm, playful young adventurer voice.",
        "previewText": "Heya! It's me, Imoen. Ready when you are.",
        "voiceDesignConfig": {"numberOfSamples": 1},
    }
    synthesis = bodies["/tts/v1/voice:synthesizeBatch"]["items"][0]["request"]
    assert synthesis == {
        "text": "Heya!",
        "voiceId": "workspace__imoen",
        "modelId": "inworld-tts-2",
        "audioConfig": {"audioEncoding": "WAV", "sampleRateHertz": 22_050},
        "language": "en-GB",
        "deliveryMode": "BALANCED",
        "applyTextNormalization": "ON",
        "enhanceGeneration": True,
    }
    signed = [request for request in requests if request.url.host == "signed.example"]
    assert signed
    assert all("Authorization" not in request.headers for request in signed)
    authenticated = [request for request in requests if request.url.host == "api.inworld.ai"]
    assert all(request.headers["Authorization"] == "Basic secret" for request in authenticated)
    listed = [request for request in authenticated if request.url.path == "/voices/v1/voices"]
    assert [request.url.params["pageToken"] for request in listed] == ["", "next-page"]
    assert all(
        request.url.params["filter"] == 'source = "IVC" AND tags:"bgvoice"' for request in listed
    )
