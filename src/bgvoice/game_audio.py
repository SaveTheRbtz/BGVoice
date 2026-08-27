"""Encode audio into the format consumed by Baldur's Gate Enhanced Edition."""

from io import BytesIO
from typing import cast

import av
import numpy as np
import soundfile as sf
from av.audio.resampler import AudioResampler
from av.container import InputContainer
from numpy.typing import NDArray

GAME_AUDIO_MIME_TYPE = "audio/ogg"
GAME_AUDIO_SAMPLE_RATE_HERTZ = 22_050


def encode_game_audio(source: bytes) -> bytes:
    """Convert provider audio to mono Ogg Vorbis for installation as a .WAV resource."""
    assert source, "source audio is empty"
    chunks: list[NDArray[np.float32]] = []
    with cast(InputContainer, av.open(BytesIO(source))) as container:
        resampler = AudioResampler(
            format="fltp",
            layout="mono",
            rate=GAME_AUDIO_SAMPLE_RATE_HERTZ,
        )
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                chunks.append(cast(NDArray[np.float32], converted.to_ndarray()))
        for converted in resampler.resample(None):
            chunks.append(cast(NDArray[np.float32], converted.to_ndarray()))
    assert chunks, "source audio has no decodable frames"

    output = BytesIO()
    sf.write(
        output,
        np.concatenate(chunks, axis=1).T,
        GAME_AUDIO_SAMPLE_RATE_HERTZ,
        format="OGG",
        subtype="VORBIS",
        compression_level=0.0,
    )
    audio = output.getvalue()
    assert audio.startswith(b"OggS"), "audio encoder did not produce Ogg audio"
    return audio
