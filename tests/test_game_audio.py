"""Game-format audio gain, limiting, and transcoding behavior."""

import json
import math
import wave
from array import array
from io import BytesIO
from typing import cast

import av
import pytest
from av.container import InputContainer
from av.filter import loudnorm

from bgvoice.game_audio import GAME_AUDIO_BIT_RATE, encode_game_audio


def test_provider_segments_are_joined_in_the_game_format() -> None:
    first = BytesIO()
    with wave.open(first, "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(44_100)
        audio.writeframes(b"\0\0" * 2 * 4_410)

    second = BytesIO()
    with wave.open(second, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22_050)
        audio.writeframes(b"\0\0" * 2_205)

    encoded = encode_game_audio(first.getvalue() + second.getvalue())
    identification = encoded.index(b"\x01vorbis")
    with cast(InputContainer, av.open(BytesIO(encoded))) as container:
        samples = sum(frame.samples for frame in container.decode(audio=0))

    assert encoded.startswith(b"OggS")
    assert samples / 22_050 == pytest.approx(0.2, abs=0.015)
    assert encoded[identification + 11] == 1
    assert int.from_bytes(encoded[identification + 12 : identification + 16], "little") == 22_050
    assert int.from_bytes(encoded[identification + 20 : identification + 24], "little") == (
        GAME_AUDIO_BIT_RATE
    )


@pytest.mark.parametrize(("amplitude", "limited"), [(0.1, False), (0.9, True)])
def test_game_audio_raises_volume_and_protects_true_peaks(
    amplitude: float,
    limited: bool,
) -> None:
    source = BytesIO()
    with wave.open(source, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22_050)
        audio.writeframes(
            b"".join(
                int(amplitude * 32_767 * math.sin(2 * math.pi * 440 * index / 22_050)).to_bytes(
                    2, "little", signed=True
                )
                for index in range(5_512)
            )
        )

    measurements: list[float] = []
    for encoded in (source.getvalue(), encode_game_audio(source.getvalue())):
        with cast(InputContainer, av.open(BytesIO(encoded))) as container:
            raw = cast(
                dict[str, str],
                json.loads(
                    loudnorm.stats(
                        "I=-22:LRA=50:TP=-2:dual_mono=false",
                        container.streams.audio[0],
                    )
                ),
            )
        measurements.append(float(raw["input_tp"]))
    before, after = measurements

    if limited:
        assert after <= -2.0
    else:
        assert after - before == pytest.approx(3.0, abs=0.2)


def test_peak_limiter_preserves_the_end_of_short_lines() -> None:
    sample_count = 5_512
    samples = [0] * sample_count
    samples[0] = samples[-1] = 30_000
    source = BytesIO()
    with wave.open(source, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22_050)
        audio.writeframes(b"".join(sample.to_bytes(2, "little", signed=True) for sample in samples))

    decoded = array("f")
    with cast(InputContainer, av.open(BytesIO(encode_game_audio(source.getvalue())))) as container:
        for frame in container.decode(audio=0):
            assert frame.format.name == "fltp"
            decoded.frombytes(bytes(frame.planes[0])[: frame.samples * decoded.itemsize])

    assert len(decoded) == pytest.approx(sample_count, abs=256)
    assert max(abs(sample) for sample in decoded[-300:]) > 0.25
