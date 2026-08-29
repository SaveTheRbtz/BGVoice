"""Encode audio into the format consumed by Baldur's Gate Enhanced Edition."""

from fractions import Fraction
from io import BytesIO
from itertools import pairwise
from typing import cast

import av
from av.audio.frame import AudioFrame
from av.audio.resampler import AudioResampler
from av.audio.stream import AudioStream
from av.container import InputContainer
from av.filter import Graph

GAME_AUDIO_MIME_TYPE = "audio/ogg"
GAME_AUDIO_SAMPLE_RATE_HERTZ = 22_050
GAME_AUDIO_BIT_RATE = 44_000
GAME_AUDIO_GAIN_DB = 3.0
PRE_CODEC_TRUE_PEAK_DB = -2.3


def encode_game_audio(source: bytes) -> bytes:
    """Join provider segments, raise them 3 dB safely, and encode Ogg Vorbis once."""
    assert source, "source audio is empty"
    output = BytesIO()
    time_base = Fraction(1, GAME_AUDIO_SAMPLE_RATE_HERTZ)
    input_samples = 0
    output_samples = 0

    with av.open(output, mode="w", format="ogg") as destination:
        encoded = cast(
            AudioStream,
            destination.add_stream("libvorbis", rate=GAME_AUDIO_SAMPLE_RATE_HERTZ),
        )
        encoded.bit_rate = GAME_AUDIO_BIT_RATE
        encoded.layout = "mono"
        encoded.time_base = time_base
        encoded.codec_context.time_base = time_base

        graph = Graph()
        graph.threads = 1
        limit = 10 ** (PRE_CODEC_TRUE_PEAK_DB / 20)
        nodes = [
            graph.add_abuffer(
                sample_rate=GAME_AUDIO_SAMPLE_RATE_HERTZ,
                format="fltp",
                layout="mono",
                channels=1,
                time_base=time_base,
            ),
            graph.add("aresample", "192000"),
            graph.add("volume", f"volume={GAME_AUDIO_GAIN_DB:.6f}dB:precision=float"),
            graph.add(
                "alimiter",
                f"limit={limit:.9f}:attack=5:release=50:level=false:latency=true",
            ),
            graph.add("aresample", str(GAME_AUDIO_SAMPLE_RATE_HERTZ)),
            graph.add(
                "aformat",
                "sample_fmts=fltp:"
                f"sample_rates={GAME_AUDIO_SAMPLE_RATE_HERTZ}:channel_layouts=mono",
            ),
            graph.add("abuffersink"),
        ]
        for left, right in pairwise(nodes):
            left.link_to(right)
        graph.configure()

        def drain() -> None:
            nonlocal output_samples
            while True:
                try:
                    frame = cast(AudioFrame, graph.pull())
                except av.error.BlockingIOError, av.error.EOFError:
                    return
                frame.pts = output_samples
                frame.time_base = time_base
                output_samples += frame.samples
                for packet in encoded.encode(frame):
                    destination.mux(packet)

        for segment in _audio_segments(source):
            resampler = AudioResampler(
                format="fltp",
                layout="mono",
                rate=GAME_AUDIO_SAMPLE_RATE_HERTZ,
            )
            with cast(InputContainer, av.open(BytesIO(segment))) as decoded:
                for decoded_frame in decoded.decode(audio=0):
                    for frame in resampler.resample(decoded_frame):
                        frame.pts = input_samples
                        frame.time_base = time_base
                        input_samples += frame.samples
                        graph.push(frame)
                        drain()
                for frame in resampler.resample(None):
                    frame.pts = input_samples
                    frame.time_base = time_base
                    input_samples += frame.samples
                    graph.push(frame)
                    drain()

        assert input_samples, "source audio has no decodable frames"
        graph.push(None)
        drain()
        assert output_samples, "audio filter produced no frames"
        for packet in encoded.encode():
            destination.mux(packet)

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
