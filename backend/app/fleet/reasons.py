"""Why a server is red in the fleet -- the rules, all of them here (DM-154).

A closed list of reasons, each from data the box sent; a kind with no source
in that data is not a reason (the drift of a box: ``box-state.v1`` has no
field for it -- it comes with one). The page knows none of these rules: it
shows the reasons and the order the API gives.

- ``no-heartbeat`` -- ``server_states.last_heartbeat_at``: none, or older
  than 90 s (PRIMER-PANEL-TZ-2 5);
- ``verdict-unverified`` -- the last verdict's ``verified`` is false
  (PRIMER-PANEL-TZ-2 8);
- ``verdict-red`` -- the last verdict's ``result`` is ``red`` (``incomplete``
  is not);
- ``service-unhealthy`` -- in the last full ``box-state.v1`` a service's
  ``health`` is ``unhealthy`` (``starting`` is not);
- ``machine-behind`` -- ``server_states.machine_version`` is below the pinned
  release of the Panel's machine (``pridem.__version__``);
- ``ssl-due`` -- in the last full ``box-state.v1``, ``now >= renews_from``
  (the machine's own moment); ``provided``, which has none, ``now >=
  expires``.

No data is no reason: a part not measured, no full form, a version that
does not parse, a moment that is no date -- the field says "no data", the
server is not red for it (``2026-13-45T99:99:99Z`` passes the form of a
moment of ``box-state.v1`` and is none: one box must not take the fleet down
for everybody, DM-210).

The order: more reasons first; then the most senior reason (``SENIORITY``,
the order of ``RedReason``: a box not heard, a verdict not to be trusted, a
red verdict, a service down, before a machine behind and a certificate due);
then the server's name.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import pridem
from packaging.version import InvalidVersion, Version
from pridem.report.box_snapshot import BoxSnapshot, StackPart, Unmeasured

HEARTBEAT_SILENCE = timedelta(seconds=90)
PINNED_RELEASE = pridem.__version__


class RedReason(StrEnum):
    NO_HEARTBEAT = "no-heartbeat"
    VERDICT_UNVERIFIED = "verdict-unverified"
    VERDICT_RED = "verdict-red"
    SERVICE_UNHEALTHY = "service-unhealthy"
    MACHINE_BEHIND = "machine-behind"
    SSL_DUE = "ssl-due"


SENIORITY: tuple[RedReason, ...] = tuple(RedReason)


@dataclass(frozen=True)
class LastVerdict:
    result: str
    verified: bool


def moment(value: str) -> datetime | None:
    """A moment of the box (``...Z``) as a time; ``None`` -- the text has the
    form of a moment and is no date (a month 13, a day 30 of February)."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def behind(version: str | None) -> bool | None:
    """The box's machine below the pinned release; ``None`` -- not known."""
    if version is None:
        return None
    try:
        return Version(version) < Version(PINNED_RELEASE)
    except InvalidVersion:
        return None


def services(snapshot: BoxSnapshot | None) -> list[str] | None:
    """The health of every measured service of the box; ``None`` -- no data."""
    if snapshot is None or isinstance(snapshot.stacks, Unmeasured):
        return None
    found: list[str] = []
    for stack in snapshot.stacks:
        if isinstance(stack.entries, Unmeasured):
            continue
        for entry in stack.entries:
            if isinstance(entry.services, Unmeasured):
                continue
            found.extend(service.health for service in entry.services)
    return found


def stacks(snapshot: BoxSnapshot | None) -> list[StackPart] | None:
    if snapshot is None or isinstance(snapshot.stacks, Unmeasured):
        return None
    return list(snapshot.stacks)


def ssl_due(snapshot: BoxSnapshot | None, now: datetime) -> bool:
    if snapshot is None or isinstance(snapshot.ssl, Unmeasured):
        return False
    ssl = snapshot.ssl
    expires = moment(ssl.expires)
    if expires is None:
        return False  # no date is no data: not red for it
    if now >= expires:
        return True
    if not isinstance(ssl.renews_from, str):
        return False
    renews = moment(ssl.renews_from)
    return renews is not None and now >= renews


def reasons(
    *,
    heartbeat_at: datetime | None,
    machine_version: str | None,
    verdict: LastVerdict | None,
    snapshot: BoxSnapshot | None,
    now: datetime,
) -> list[RedReason]:
    """Every reason the server is red, in the order of seniority."""
    found: set[RedReason] = set()
    if heartbeat_at is None or now - heartbeat_at > HEARTBEAT_SILENCE:
        found.add(RedReason.NO_HEARTBEAT)
    if verdict is not None and not verdict.verified:
        found.add(RedReason.VERDICT_UNVERIFIED)
    if verdict is not None and verdict.result == "red":
        found.add(RedReason.VERDICT_RED)
    if "unhealthy" in (services(snapshot) or []):
        found.add(RedReason.SERVICE_UNHEALTHY)
    if behind(machine_version):
        found.add(RedReason.MACHINE_BEHIND)
    if ssl_due(snapshot, now):
        found.add(RedReason.SSL_DUE)
    return [reason for reason in SENIORITY if reason in found]


def order_key(name: str, found: list[RedReason]) -> tuple[int, int, str]:
    """More reasons first, then the most senior one, then the name."""
    senior = min((SENIORITY.index(reason) for reason in found), default=len(SENIORITY))
    return (-len(found), senior, name)
