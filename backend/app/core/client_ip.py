"""The client's address, for the limits and, later, the audit trail.

Translated from velo ``core/middleware.py`` (``_extract_client_ip``, BE-40 and
T-47); aivis ``core/client_ip.py`` takes ``X-Real-IP`` from any peer and is
not followed.

THE RULE. The address is ``X-Real-IP``, taken ONLY when the request came from
the Panel's own reverse proxy -- the deploy machine's nginx, which sets the
header to the address of the connection it accepted (``proxy_set_header
X-Real-IP $remote_addr``) and so replaces anything a client wrote -- and only
when the value is an address of at most ``MAX_CLIENT_IP_LEN`` characters.
Otherwise the TCP peer itself. ``X-Forwarded-For`` is never read: its usual
form appends to what the sender wrote, so its first hop is the sender's
choice.

"FROM OUR PROXY" is read from the deployment, not a setting: behind the
machine's nginx the peer is a container on a private network; a public peer
did not come through the proxy, and then the peer IS the client. The peer is
the one the OS reported because uvicorn runs with ``--no-proxy-headers``
(backend/Dockerfile): with proxy headers on, uvicorn would itself rewrite the
peer from ``X-Forwarded-For``.

A proxy in front of nginx (a CDN, a balancer) is configured in nginx
(``real_ip``), never here: the application trusts exactly one hop.

The length cap runs before the parse: an IPv6 address with a scope id of any
length still parses, and the audit column will hold 45 characters.
"""

import ipaddress

from fastapi import Request

MAX_CLIENT_IP_LEN = 45
"""The longest textual IPv6 address with an embedded IPv4 one."""

_REAL_IP = b"x-real-ip"


def _address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def peer_is_trusted(peer: str | None) -> bool:
    """The peer is our own proxy: a loopback or private address.

    ``is_private`` of CPython 3.12 is wider than RFC 1918 (link-local and the
    documentation ranges too); a real peer is either the proxy on the docker
    network or a routable client, never a documentation address.
    """
    if not peer:
        return False
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def client_ip(request: Request) -> str | None:
    """The client's address by the rule above; ``None`` with no peer at all."""
    client = request.scope.get("client")
    peer = str(client[0]) if client else None
    if peer_is_trusted(peer):
        for name, value in request.scope.get("headers", []):
            if name != _REAL_IP:
                continue
            real = bytes(value).decode("latin-1")
            if real and len(real) <= MAX_CLIENT_IP_LEN and _address(real):
                return real
            break
    return peer
