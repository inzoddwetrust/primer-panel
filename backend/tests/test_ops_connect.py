"""ssh's way out of the Panel's container (DM-158): ``app.ops.connect`` as ssh
runs it, a process with stdin and stdout, against a stand-in proxy on
localhost. The proxy of a box (squid, CONNECT to 443) is measured live only
on DM-160."""

import os
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Stand:
    """One connection: it records the request's head, answers ``status``
    and, when it is 200, sends back what it gets until the other side ends."""

    def __init__(self, status: bytes | None) -> None:
        self.status = status
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.head = b""
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        conn, _ = self.server.accept()
        with conn:
            if self.status is not None:
                while b"\r\n\r\n" not in self.head:
                    self.head += conn.recv(1024)
                conn.sendall(self.status + b"\r\n\r\n")
                if not self.status.startswith(b"HTTP/1.1 200"):
                    return
            while chunk := conn.recv(1024):
                conn.sendall(chunk)

    def close(self) -> None:
        self.thread.join(5)
        self.server.close()


@pytest.fixture
def stands() -> Iterator[list[Stand]]:
    made: list[Stand] = []
    yield made
    for stand in made:
        stand.close()


def connect(
    host: str, port: int, proxy: str | None
) -> subprocess.CompletedProcess[bytes]:
    env = {
        k: v for k, v in os.environ.items() if k not in ("HTTPS_PROXY", "https_proxy")
    }
    env["PYTHONPATH"] = BACKEND
    if proxy is not None:
        env["HTTPS_PROXY"] = proxy
    return subprocess.run(
        [sys.executable, "-m", "app.ops.connect", host, str(port)],
        input=b"ssh speaks\n",
        capture_output=True,
        env=env,
        timeout=20,
        check=False,
    )


def test_through_the_proxy(stands: list[Stand]) -> None:
    proxy = Stand(b"HTTP/1.1 200 Connection established")
    stands.append(proxy)
    done = connect("ssh.github.com", 443, f"http://127.0.0.1:{proxy.port}")
    assert done.returncode == 0, done.stderr
    assert done.stdout == b"ssh speaks\n"
    first = proxy.head.split(b"\r\n", 1)[0]
    assert first == b"CONNECT ssh.github.com:443 HTTP/1.1"
    assert b"\r\nHost: ssh.github.com:443\r\n" in proxy.head


def test_a_tunnel_the_proxy_refuses(stands: list[Stand]) -> None:
    proxy = Stand(b"HTTP/1.1 403 Forbidden")
    stands.append(proxy)
    done = connect("ssh.github.com", 443, f"http://127.0.0.1:{proxy.port}")
    assert done.returncode == 1
    assert b"403 Forbidden" in done.stderr
    assert done.stdout == b""


def test_without_a_proxy_straight(stands: list[Stand]) -> None:
    target = Stand(None)
    stands.append(target)
    done = connect("127.0.0.1", target.port, None)
    assert done.returncode == 0, done.stderr
    assert done.stdout == b"ssh speaks\n"
