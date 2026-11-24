"""A stand-in box for the tests of the agent's paths (DM-153).

It holds an ed25519 pair (``cryptography``), registers by a one-time token
and signs every request as contract 4 says: ``signing_string`` of
``pridem.protocol`` -- the method, the path, the time and the SHA-256 of the
body -- with its private key, base64. Its messages are the models of
contract 4 dumped to JSON, or bytes as a test writes them.

A test spoils one part of a request at a time: the signature, the body, the
time, the box, the version.
"""

import base64
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient
from pridem.protocol import (
    BOX_HEADER,
    PROTOCOL_HEADER,
    SIGNATURE_HEADER,
    TIME_HEADER,
    signing_string,
)
from pydantic import BaseModel

AGENT = "/agent/v1"

# A run of the box, as its journal and history/ hold it (contract 2, DM-137).
RUN_ID = "2026-11-24T12:00:00Z-ab12"


def header_line(run_id: str = RUN_ID, verb: str = "status") -> dict[str, object]:
    return {
        "event": "header",
        "seq": 1,
        "at": "2026-11-24T12:00:00.000Z",
        "run_id": run_id,
        "verb": verb,
        "mode": "status",
        "args": {},
        "actor": {"type": "engineer", "via": "local"},
        "started": "2026-11-24T12:00:00Z",
        "composition_before": {"pridem": "0.1.8"},
    }


def log_line(seq: int) -> dict[str, object]:
    return {
        "event": "log",
        "seq": seq,
        "at": f"2026-11-24T12:00:{seq:02d}.000Z",
        "phase": "main",
        "stack": "velo",
        "name": "build",
        "stream": "stdout",
        "line": f"line {seq}",
    }


def finished_line(seq: int) -> dict[str, object]:
    return {
        "event": "run_finished",
        "seq": seq,
        "at": f"2026-11-24T12:00:{seq:02d}.000Z",
        "exit_code": 0,
        "result": "green",
    }


def verdict(run_id: str = RUN_ID) -> dict[str, object]:
    return {
        "schema": 1,
        "run_id": run_id,
        "verb": "status",
        "args": {},
        "actor": {"type": "engineer", "via": "local"},
        "started": "2026-11-24T12:00:00Z",
        "finished": "2026-11-24T12:00:05Z",
        "exit_code": 0,
        "result": "green",
        "composition_before": {"pridem": "0.1.8"},
        "composition_after": {"pridem": "0.1.8"},
        "steps": [],
        "report": {"failures": [], "incomplete": []},
    }


@dataclass
class FakeBox:
    client: TestClient
    key: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)
    box_id: str | None = None

    @property
    def public(self) -> str:
        raw = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return base64.b64encode(raw).decode()

    def sign(self, message: bytes) -> str:
        return base64.b64encode(self.key.sign(message)).decode()

    def register(
        self, token: str, name: str, repo: str, protocol: str = "1"
    ) -> httpx.Response:
        body = {
            "token": token,
            "server_name": name,
            "role": "test",
            "product_repo": repo,
            "machine_version": "0.1.8",
            "box_key_public": self.public,
        }
        response = self.request(
            "POST",
            f"{AGENT}/register",
            json.dumps(body).encode(),
            {PROTOCOL_HEADER: protocol, "Content-Type": "application/json"},
        )
        if response.status_code == 201:
            self.box_id = response.json()["box_id"]
        return response

    def headers(
        self,
        method: str,
        path: str,
        body: bytes,
        *,
        at: int | None = None,
        protocol: str = "1",
        box: str | None = None,
    ) -> dict[str, str]:
        moment = int(time.time()) if at is None else at
        signed = signing_string(method, path, moment, body).encode()
        return {
            BOX_HEADER: box if box is not None else (self.box_id or ""),
            TIME_HEADER: str(moment),
            SIGNATURE_HEADER: self.sign(signed),
            PROTOCOL_HEADER: protocol,
            "Content-Type": "application/json",
        }

    def send(
        self,
        method: str,
        path: str,
        message: BaseModel | Mapping[str, object] | bytes | None = None,
        **spoil: object,
    ) -> httpx.Response:
        """A signed request of the box; ``spoil`` changes a header after the
        signing (``signature``, ``time``, ``box``, ``protocol``) or the body
        (``body``), or signs at another moment (``at``)."""
        if isinstance(message, BaseModel):
            body = message.model_dump_json(by_alias=True).encode()
        elif isinstance(message, Mapping):
            body = json.dumps(dict(message)).encode()
        else:
            body = message or b""
        full = AGENT + path
        at = spoil.get("at")
        headers = self.headers(
            method, full, body, at=at if isinstance(at, int) else None
        )
        for name, header in (
            ("signature", SIGNATURE_HEADER),
            ("time", TIME_HEADER),
            ("box", BOX_HEADER),
            ("protocol", PROTOCOL_HEADER),
        ):
            if name in spoil:
                value = spoil[name]
                if value is None:
                    headers.pop(header)
                else:
                    headers[header] = str(value)
        sent = spoil.get("body", body)
        assert isinstance(sent, bytes)
        return self.request(method, full, sent, headers)

    def request(
        self, method: str, path: str, body: bytes, headers: dict[str, str]
    ) -> httpx.Response:
        """As a box sends it: no ``Origin`` -- a box is no browser, whatever
        the test's client carries by default."""
        built = self.client.build_request(method, path, content=body, headers=headers)
        built.headers.pop("origin", None)
        response: httpx.Response = self.client.send(built)
        return response
