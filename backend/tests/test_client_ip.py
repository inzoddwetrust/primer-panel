"""The client's address: X-Real-IP from our own proxy only, else the peer."""

import pytest
from starlette.requests import Request

from app.core.client_ip import MAX_CLIENT_IP_LEN, client_ip

PROXY = "172.18.0.5"  # the machine's nginx on the docker network
PUBLIC = "93.184.216.34"
CLIENT = "198.18.0.9"
LONG = "fe80::1%" + "a" * 40  # an address, by the parser, longer than the cap


def _request(peer: str | None, *headers: tuple[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        # ASGI: header names arrive lower-case
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers],
        "client": (peer, 40000) if peer is not None else None,
    }
    return Request(scope)


@pytest.mark.parametrize(
    ("peer", "headers", "address"),
    [
        (PROXY, [("X-Real-IP", PUBLIC)], PUBLIC),
        ("127.0.0.1", [("X-Real-IP", PUBLIC)], PUBLIC),
        (PROXY, [("X-Real-IP", "2001:db8::7")], "2001:db8::7"),
        (PROXY, [], PROXY),
        (PROXY, [("X-Real-IP", "")], PROXY),
        (PROXY, [("X-Real-IP", "not-an-address")], PROXY),
        (PROXY, [("X-Real-IP", LONG)], PROXY),
        (PROXY, [("X-Forwarded-For", PUBLIC)], PROXY),
        (PROXY, [("X-Forwarded-For", CLIENT), ("X-Real-IP", PUBLIC)], PUBLIC),
        (PUBLIC, [("X-Real-IP", CLIENT)], PUBLIC),
        (PUBLIC, [("X-Forwarded-For", CLIENT)], PUBLIC),
        ("testclient", [("X-Real-IP", PUBLIC)], "testclient"),
        (None, [("X-Real-IP", PUBLIC)], None),
    ],
    ids=[
        "proxy-header",
        "loopback-header",
        "proxy-ipv6",
        "proxy-no-header",
        "proxy-empty",
        "proxy-not-an-address",
        "proxy-over-the-cap",
        "proxy-forwarded-only",
        "proxy-forwarded-ignored",
        "public-peer-header-ignored",
        "public-peer-forwarded-ignored",
        "peer-not-an-address",
        "no-peer",
    ],
)
def test_the_address_of_the_client(
    peer: str | None, headers: list[tuple[str, str]], address: str | None
) -> None:
    assert client_ip(_request(peer, *headers)) == address


def test_the_cap_is_the_column_and_runs_before_the_parse() -> None:
    """An address of exactly the cap is taken; one over it -- the peer, though
    the parser takes it (a scope id of any length is an address)."""
    at_cap = "0000:0000:0000:0000:0000:ffff:255.255.255.255"
    assert len(at_cap) == MAX_CLIENT_IP_LEN
    assert client_ip(_request(PROXY, ("X-Real-IP", at_cap))) == at_cap
    assert len(LONG) > MAX_CLIENT_IP_LEN
    assert client_ip(_request(PROXY, ("X-Real-IP", LONG))) == PROXY
