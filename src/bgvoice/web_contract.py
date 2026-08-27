"""Typed, transport-independent contracts for the read-only web API."""

import base64
import hashlib
import re
import unicodedata
from enum import StrEnum
from typing import Final, Literal, NewType

from pydantic import BaseModel, ConfigDict, Field

type InstallationId = Literal["bg2ee-eet"]

INSTALLATION_ID: Final[InstallationId] = "bg2ee-eet"

ResourceId = NewType("ResourceId", str)
ResourceName = NewType("ResourceName", str)


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
    CAMPAIGNS = "campaigns"
    EXTRACTION_RUNS = "extractionRuns"


class ResourceView(StrEnum):
    BASIC = "basic"
    FULL = "full"


_RESOURCE_ID = re.compile(r"^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_DIGEST_BYTES = 4
_MAX_RESOURCE_ID_LENGTH = 63


def resource_id(raw: str) -> ResourceId:
    """Return a stable RFC-1034 resource ID for an Infinity Engine identifier."""
    canonical = raw.casefold()
    if _RESOURCE_ID.fullmatch(canonical):
        return ResourceId(canonical)

    ascii_text = unicodedata.normalize("NFKD", canonical).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if not normalized or not normalized[0].isalpha():
        normalized = f"r-{normalized}" if normalized else "r"

    digest = hashlib.blake2s(canonical.encode(), digest_size=_DIGEST_BYTES).hexdigest()
    stem_length = _MAX_RESOURCE_ID_LENGTH - len(digest) - 1
    stem = normalized[:stem_length].rstrip("-")
    return ResourceId(f"{stem}-{digest}")


def resource_name(collection: Collection, raw_id: str) -> ResourceName:
    """Return the canonical name of one resource in the EET installation."""
    return ResourceName(f"installations/{INSTALLATION_ID}/{collection}/{resource_id(raw_id)}")


class _PageToken(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    collection: Collection
    filter: str
    order_by: str
    view: ResourceView
    page_size: int = Field(gt=0)
    offset: int = Field(ge=0)


def encode_page_token(
    collection: Collection,
    *,
    filter: str,
    order_by: str,
    view: ResourceView,
    page_size: int,
    offset: int,
) -> str:
    """Encode a typed, request-bound opaque pagination cursor."""
    assert page_size > 0, "page-token page size must be positive"
    assert offset >= 0, "page-token offset must not be negative"
    cursor = _PageToken(
        collection=collection,
        filter=filter,
        order_by=order_by,
        view=view,
        page_size=page_size,
        offset=offset,
    )
    return _base64url_encode(cursor.model_dump_json().encode())


def decode_page_token(
    token: str,
    collection: Collection,
    *,
    filter: str,
    order_by: str,
    view: ResourceView,
    page_size: int,
) -> int:
    """Decode a cursor and require it to match the rest of the List request."""
    cursor = _PageToken.model_validate_json(_base64url_decode(token))
    expected = _PageToken(
        collection=collection,
        filter=filter,
        order_by=order_by,
        view=view,
        page_size=page_size,
        offset=cursor.offset,
    )
    if cursor != expected:
        raise ValueError("page token does not match the request")
    return cursor.offset


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    if _base64url_encode(decoded) != value:
        raise ValueError("invalid page token encoding")
    return decoded
