"""ssh's way out of the Panel's container (DM-158): ``ProxyCommand``.

    python -m app.ops.connect <host> <port>

The machine puts every service of a product behind its proxy: the container
has no route out but ``HTTPS_PROXY``, which opens ``CONNECT`` to port 443 of
the names of ``egress`` (TZ 0.7.33 C, 0.7.46). ``ssh`` to
``ssh.github.com:443`` goes through it: this asks the proxy for the tunnel and
then copies stdin to the tunnel and the tunnel to stdout, until either side
ends. Without ``HTTPS_PROXY`` it connects directly. A proxy that refuses the
tunnel ends it with exit code 1 and the proxy's status line on stderr.
"""

import os
import socket
import sys
import threading
from urllib.parse import urlsplit

TIMEOUT_S = 30.0
"""How long the connection and the proxy's answer may take."""

_HEAD_MAX = 16384


def _proxy() -> tuple[str, int] | None:
    found = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not found:
        return None
    parts = urlsplit(found if "://" in found else f"http://{found}")
    if parts.hostname is None:
        raise ValueError("HTTPS_PROXY names no host")
    return parts.hostname, parts.port or 3128


def _tunnel(host: str, port: int) -> socket.socket:
    proxy = _proxy()
    if proxy is None:
        return socket.create_connection((host, port), timeout=TIMEOUT_S)
    sock = socket.create_connection(proxy, timeout=TIMEOUT_S)
    target = f"{host}:{port}"
    sock.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = sock.recv(4096)
        if not chunk or len(head) > _HEAD_MAX:
            sock.close()
            raise ConnectionError("the proxy ended before its answer")
        head += chunk
    status, _, rest = head.partition(b"\r\n\r\n")
    line = status.split(b"\r\n", 1)[0]
    words = line.split()
    if len(words) < 2 or words[1] != b"200":
        sock.close()
        raise ConnectionError(line.decode("ascii", "replace"))
    if rest:
        _out(rest)
    return sock


def _out(chunk: bytes) -> None:
    sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()


def _outward(sock: socket.socket) -> None:
    while chunk := os.read(sys.stdin.fileno(), 65536):
        sock.sendall(chunk)
    sock.shutdown(socket.SHUT_WR)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1].isdigit():
        print("usage: python -m app.ops.connect <host> <port>", file=sys.stderr)
        return 2
    try:
        sock = _tunnel(argv[0], int(argv[1]))
    except (OSError, ValueError) as error:
        print(f"connect: {error}", file=sys.stderr)
        return 1
    sock.settimeout(None)
    threading.Thread(target=_outward, args=(sock,), daemon=True).start()
    while chunk := sock.recv(65536):
        _out(chunk)
    sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
