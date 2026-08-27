"""Tests for transport-independent web resource contracts."""

import hashlib
import re

import pytest

from bgvoice.web_contract import (
    INSTALLATION_ID,
    Collection,
    ResourceView,
    decode_page_token,
    encode_page_token,
    resource_id,
    resource_name,
)

_AIP_RESOURCE_ID = re.compile(r"^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def test_resource_id_leaves_conforming_values_plain_and_lowercases_them() -> None:
    assert resource_id("imoen2j") == "imoen2j"
    assert resource_id("IMOEN2J") == "imoen2j"
    assert resource_id("A" * 63) == "a" * 63


def test_resource_id_normalizes_and_hashes_changed_values() -> None:
    raw = "Éowyn's CRE/1"
    digest = hashlib.blake2s(raw.casefold().encode(), digest_size=4).hexdigest()

    assert resource_id(raw) == f"eowyn-s-cre-1-{digest}"
    assert resource_id(raw) == resource_id(raw.swapcase())
    assert resource_id("A_B") != resource_id("A B")
    assert resource_id("A_B").startswith("a-b-")


@pytest.mark.parametrize("raw", ["", "123", "☃", "a" * 64, "-trailing-"])
def test_resource_id_always_has_an_aip_safe_bounded_result(raw: str) -> None:
    result = resource_id(raw)

    assert len(result) <= 63
    assert _AIP_RESOURCE_ID.fullmatch(result)
    assert result[0].isalpha()
    assert result[-1].isalnum()
    assert result == resource_id(raw)


def test_resource_name_uses_the_canonical_installation_parent() -> None:
    assert INSTALLATION_ID == "bg2ee-eet"
    assert (
        resource_name(Collection.CHARACTERS, "IMOEN2J")
        == "installations/bg2ee-eet/characters/imoen2j"
    )


def test_page_tokens_round_trip_deterministically_and_are_url_safe() -> None:
    arguments = {
        "filter": 'display_name = "Imoen"',
        "order_by": "npc_line_count desc",
        "view": ResourceView.FULL,
        "page_size": 50,
    }

    token = encode_page_token(Collection.VOICES, **arguments, offset=150)

    assert token == encode_page_token(Collection.VOICES, **arguments, offset=150)
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)
    assert decode_page_token(token, Collection.VOICES, **arguments) == 150


@pytest.mark.parametrize(
    ("collection", "filter", "order_by", "view", "page_size"),
    [
        (Collection.CHARACTERS, "speaker = imoen", "name", ResourceView.BASIC, 50),
        (Collection.VOICES, "speaker = jaheira", "name", ResourceView.BASIC, 50),
        (Collection.VOICES, "speaker = imoen", "name desc", ResourceView.BASIC, 50),
        (Collection.VOICES, "speaker = imoen", "name", ResourceView.FULL, 50),
        (Collection.VOICES, "speaker = imoen", "name", ResourceView.BASIC, 100),
    ],
)
def test_page_tokens_reject_reuse_with_a_changed_request(
    collection: Collection,
    filter: str,
    order_by: str,
    view: ResourceView,
    page_size: int,
) -> None:
    token = encode_page_token(
        Collection.VOICES,
        filter="speaker = imoen",
        order_by="name",
        view=ResourceView.BASIC,
        page_size=50,
        offset=50,
    )

    with pytest.raises(ValueError, match="does not match"):
        decode_page_token(
            token,
            collection,
            filter=filter,
            order_by=order_by,
            view=view,
            page_size=page_size,
        )


def test_page_tokens_reject_malformed_payloads() -> None:
    arguments = {
        "filter": "",
        "order_by": "",
        "view": ResourceView.BASIC,
        "page_size": 50,
    }
    token = encode_page_token(Collection.VOICES, **arguments, offset=50)

    with pytest.raises(ValueError):
        decode_page_token(f"{token}A", Collection.VOICES, **arguments)


@pytest.mark.parametrize("token", ["", "one-part", "a.b.c", "$.$", "=.="])
def test_page_tokens_reject_malformed_tokens(token: str) -> None:
    with pytest.raises(ValueError):
        decode_page_token(
            token,
            Collection.VOICES,
            filter="",
            order_by="",
            view=ResourceView.BASIC,
            page_size=50,
        )


def test_page_tokens_reject_negative_offsets_and_page_sizes() -> None:
    with pytest.raises(AssertionError, match="offset"):
        encode_page_token(
            Collection.VOICES,
            filter="",
            order_by="",
            view=ResourceView.BASIC,
            page_size=50,
            offset=-1,
        )
    with pytest.raises(AssertionError, match="page size"):
        encode_page_token(
            Collection.VOICES,
            filter="",
            order_by="",
            view=ResourceView.BASIC,
            page_size=0,
            offset=0,
        )
