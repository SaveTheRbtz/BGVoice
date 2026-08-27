"""Encode audio into the format consumed by Baldur's Gate Enhanced Edition."""

from fractions import Fraction
from io import BytesIO
from typing import cast

import av
from av.audio.resampler import AudioResampler
from av.audio.stream import AudioStream
from av.container import InputContainer

GAME_AUDIO_MIME_TYPE = "audio/ogg"
GAME_AUDIO_SAMPLE_RATE_HERTZ = 22_050
GAME_AUDIO_BIT_RATE = 90_000


def encode_game_audio(source: bytes) -> bytes:
    """Convert provider audio to mono Ogg Vorbis for installation as a .WAV resource."""
    assert source, "source audio is empty"
    output = BytesIO()
    samples = 0
    time_base = Fraction(1, GAME_AUDIO_SAMPLE_RATE_HERTZ)
    with av.open(output, mode="w", format="ogg") as encoded:
        stream = cast(
            AudioStream,
            encoded.add_stream("libvorbis", rate=GAME_AUDIO_SAMPLE_RATE_HERTZ),
        )
        stream.bit_rate = GAME_AUDIO_BIT_RATE
        stream.layout = "mono"
        stream.time_base = time_base
        stream.codec_context.time_base = time_base

        for segment in _audio_segments(source):
            resampler = AudioResampler(
                format="fltp",
                layout="mono",
                rate=GAME_AUDIO_SAMPLE_RATE_HERTZ,
            )
            with cast(InputContainer, av.open(BytesIO(segment))) as decoded:
                for decoded_frame in decoded.decode(audio=0):
                    for frame in resampler.resample(decoded_frame):
                        frame.pts = samples
                        frame.time_base = time_base
                        samples += frame.samples
                        for packet in stream.encode(frame):
                            encoded.mux(packet)
                for frame in resampler.resample(None):
                    frame.pts = samples
                    frame.time_base = time_base
                    samples += frame.samples
                    for packet in stream.encode(frame):
                        encoded.mux(packet)

        assert samples, "source audio has no decodable frames"
        for packet in stream.encode():
            encoded.mux(packet)

    audio = output.getvalue()
    assert audio.startswith(b"OggS"), "audio encoder did not produce Ogg audio"
    return audio


def _audio_segments(source: bytes) -> list[bytes]:
    """Split the batch API's concatenated RIFF stream into independently decodable WAVs."""
    if not source.startswith(b"RIFF"):
        return [source]

    segments: list[bytes] = []
    offset = 0
    while offset < len(source):
        assert source[offset : offset + 4] == b"RIFF", "WAV segment is missing its RIFF header"
        end = offset + 8 + int.from_bytes(source[offset + 4 : offset + 8], "little")
        assert source[offset + 8 : offset + 12] == b"WAVE", "RIFF segment is not WAV audio"
        assert end <= len(source), "WAV segment extends beyond the downloaded audio"
        segments.append(source[offset:end])
        offset = end
    return segments
