"""Typed, transport-independent contracts for the read-only web API."""

import base64
import hashlib
import re
import struct
import unicodedata
from enum import StrEnum
from typing import Final, Literal

type InstallationId = Literal["bg2ee-eet"]

INSTALLATION_ID: Final[InstallationId] = "bg2ee-eet"
INSTALLATION_NAME: Final = f"installations/{INSTALLATION_ID}"


class Collection(StrEnum):
    VOICES = "voices"
    CHARACTERS = "characters"
    DIALOGUES = "dialogues"
    DIALOGUE_LINES = "dialogueLines"
    CHARACTER_SOUNDS = "characterSounds"
    DIALOGUE_TRANSITIONS = "dialogueTransitions"
    PORTRAITS = "portraits"
    RACES = "races"
    CHARACTER_CLASSES = "characterClasses"
    KITS = "kits"
    IDENTIFIER_DEFINITIONS = "identifierDefinitions"
    EXTRACTION_RUNS = "extractionRuns"


_RESOURCE_ID = re.compile(r"^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_DIGEST_BYTES = 4
_MAX_RESOURCE_ID_LENGTH = 63
_PAGE_TOKEN = struct.Struct(">Q16s")


def resource_id(raw: str) -> str:
    """Return a stable RFC-1034 resource ID for an Infinity Engine identifier."""
    canonical = raw.casefold()
    if _RESOURCE_ID.fullmatch(canonical):
        return canonical

    ascii_text = unicodedata.normalize("NFKD", canonical).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if not normalized or not normalized[0].isalpha():
        normalized = f"r-{normalized}" if normalized else "r"

    digest = hashlib.blake2s(canonical.encode(), digest_size=_DIGEST_BYTES).hexdigest()
    stem_length = _MAX_RESOURCE_ID_LENGTH - len(digest) - 1
    stem = normalized[:stem_length].rstrip("-")
    return f"{stem}-{digest}"


def resource_name(collection: Collection, raw_id: str) -> str:
    """Return the canonical name of one resource in the EET installation."""
    return f"{INSTALLATION_NAME}/{collection}/{resource_id(raw_id)}"


def encode_page_token(
    collection: Collection,
    *,
    filter: str,
    order_by: str,
    offset: int,
) -> str:
    """Encode a typed, request-bound opaque pagination cursor."""
    assert offset >= 0, "page-token offset must not be negative"
    return _base64url_encode(
        _PAGE_TOKEN.pack(offset, _request_fingerprint(collection, filter, order_by))
    )


def decode_page_token(
    token: str,
    collection: Collection,
    *,
    filter: str,
    order_by: str,
) -> int:
    """Decode a cursor and require it to match the rest of the List request."""
    try:
        offset, fingerprint = _PAGE_TOKEN.unpack(_base64url_decode(token))
    except struct.error as error:
        raise ValueError("invalid page token") from error
    if fingerprint != _request_fingerprint(collection, filter, order_by):
        raise ValueError("page token does not match the request")
    return int(offset)


def _request_fingerprint(collection: Collection, filter: str, order_by: str) -> bytes:
    request = "\0".join((collection, filter, order_by)).encode()
    return hashlib.blake2s(request, digest_size=16).digest()


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    if _base64url_encode(decoded) != value:
        raise ValueError("invalid page token encoding")
    return decoded
