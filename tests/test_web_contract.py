"""Stable resource names and opaque pagination tokens."""

import re

import pytest

from bgvoice.web_contract import (
    Collection,
    ResourceView,
    decode_page_token,
    encode_page_token,
    resource_id,
    resource_name,
)

_SAFE_ID = re.compile(r"^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_FILTER = 'display_name = "Imoen"'
_ORDER_BY = "npc_line_count desc"
_VIEW = ResourceView.FULL
_PAGE_SIZE = 50


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
        view=_VIEW,
        page_size=_PAGE_SIZE,
        offset=150,
    )

    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)
    assert token == encode_page_token(
        Collection.VOICES,
        filter=_FILTER,
        order_by=_ORDER_BY,
        view=_VIEW,
        page_size=_PAGE_SIZE,
        offset=150,
    )
    assert (
        decode_page_token(
            token,
            Collection.VOICES,
            filter=_FILTER,
            order_by=_ORDER_BY,
            view=_VIEW,
            page_size=_PAGE_SIZE,
        )
        == 150
    )


@pytest.mark.parametrize(
    ("collection", "filter", "order_by", "view", "page_size"),
    [
        (Collection.CHARACTERS, _FILTER, _ORDER_BY, _VIEW, _PAGE_SIZE),
        (Collection.VOICES, 'display_name = "Jaheira"', _ORDER_BY, _VIEW, _PAGE_SIZE),
        (Collection.VOICES, _FILTER, "npc_line_count asc", _VIEW, _PAGE_SIZE),
        (Collection.VOICES, _FILTER, _ORDER_BY, ResourceView.BASIC, _PAGE_SIZE),
        (Collection.VOICES, _FILTER, _ORDER_BY, _VIEW, 100),
    ],
)
def test_page_tokens_cannot_be_reused_for_a_different_request(
    collection: Collection,
    filter: str,
    order_by: str,
    view: ResourceView,
    page_size: int,
) -> None:
    token = encode_page_token(
        Collection.VOICES,
        filter=_FILTER,
        order_by=_ORDER_BY,
        view=_VIEW,
        page_size=_PAGE_SIZE,
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


@pytest.mark.parametrize("token", ["", "one-part", "a.b.c", "$.$", "=.=", "tamperedA"])
def test_page_tokens_reject_malformed_data(token: str) -> None:
    if token == "tamperedA":
        token = (
            encode_page_token(
                Collection.VOICES,
                filter=_FILTER,
                order_by=_ORDER_BY,
                view=_VIEW,
                page_size=_PAGE_SIZE,
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
            view=_VIEW,
            page_size=_PAGE_SIZE,
        )
