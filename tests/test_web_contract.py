"""Stable resource names and opaque pagination tokens."""

import base64
import re

import pytest

from bgvoice.web_contract import (
    Collection,
    decode_page_token,
    encode_page_token,
    resource_id,
    resource_name,
)

_SAFE_ID = re.compile(r"^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_FILTER = 'display_name = "Imoen"'
_ORDER_BY = "npc_line_count desc"


@pytest.mark.parametrize(
    ("raw", "prefix", "unchanged"),
    [
        ("IMOEN2J", "imoen2j", True),
        ("A" * 63, "a" * 63, True),
        ("Éowyn's CRE/1", "eowyn-s-cre-1-", False),
        ("A_B", "a-b-", False),
        ("", "r-", False),
        ("123", "r-123-", False),
        ("☃", "r-", False),
        ("a" * 64, "a" * 54, False),
    ],
)
def test_resource_ids_are_stable_safe_and_collision_preserving(
    raw: str,
    prefix: str,
    unchanged: bool,
) -> None:
    identifier = resource_id(raw)

    assert identifier.startswith(prefix)
    assert _SAFE_ID.fullmatch(identifier)
    assert len(identifier) <= 63
    assert identifier == resource_id(raw.swapcase())
    assert (identifier == raw.casefold()) is unchanged


def test_resource_names_use_the_canonical_collection_parent() -> None:
    assert (
        resource_name(Collection.CHARACTERS, "IMOEN2J")
        == "installations/bg2ee-eet/characters/imoen2j"
    )


def test_page_tokens_round_trip_and_bind_the_complete_request() -> None:
    token = encode_page_token(
        Collection.VOICES,
        filter=_FILTER,
        order_by=_ORDER_BY,
        offset=150,
    )

    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)
    assert token == encode_page_token(
        Collection.VOICES,
        filter=_FILTER,
        order_by=_ORDER_BY,
        offset=150,
    )
    assert (
        decode_page_token(
            token,
            Collection.VOICES,
            filter=_FILTER,
            order_by=_ORDER_BY,
        )
        == 150
    )
    decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    assert _FILTER.encode() not in decoded
    assert _ORDER_BY.encode() not in decoded


@pytest.mark.parametrize(
    ("collection", "filter", "order_by"),
    [
        (Collection.CHARACTERS, _FILTER, _ORDER_BY),
        (Collection.VOICES, 'display_name = "Jaheira"', _ORDER_BY),
        (Collection.VOICES, _FILTER, "npc_line_count asc"),
    ],
)
def test_page_tokens_cannot_be_reused_for_a_different_request(
    collection: Collection,
    filter: str,
    order_by: str,
) -> None:
    token = encode_page_token(
        Collection.VOICES,
        filter=_FILTER,
        order_by=_ORDER_BY,
        offset=50,
    )

    with pytest.raises(ValueError, match="does not match"):
        decode_page_token(
            token,
            collection,
            filter=filter,
            order_by=order_by,
        )


@pytest.mark.parametrize("token", ["", "one-part", "a.b.c", "$.$", "=.=", "tamperedA"])
def test_page_tokens_reject_malformed_data(token: str) -> None:
    if token == "tamperedA":
        token = (
            encode_page_token(
                Collection.VOICES,
                filter=_FILTER,
                order_by=_ORDER_BY,
                offset=50,
            )
            + "A"
        )
    with pytest.raises(ValueError):
        decode_page_token(
            token,
            Collection.VOICES,
            filter=_FILTER,
            order_by=_ORDER_BY,
        )
