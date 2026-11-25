"""The state of a run, by the box's own fields -- no timer of the Panel's
(gate DM-156, R3); the page knows none of this.

- ``finished`` -- the run has ended: its line ``run_finished`` or its verdict
  came (``runs.ended_at``, DM-153);
- ``silent`` -- else the box is not heard: no heartbeat, or none for 90 s
  (the fleet's threshold, ``app.fleet.reasons``) -- the run may go on;
- ``abandoned`` -- else the box says its journal is left without a verdict
  (``journals_without_verdict``) and nobody holds its lock
  (``lock_open_by`` empty): the run stopped and will not end;
- ``running`` -- else.
"""

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from app.fleet.reasons import HEARTBEAT_SILENCE


class RunStatus(StrEnum):
    RUNNING = "running"
    FINISHED = "finished"
    ABANDONED = "abandoned"
    SILENT = "silent"


ENDED = frozenset({RunStatus.FINISHED, RunStatus.ABANDONED})
"""The states after which a run's stream closes."""


def dead(
    run_id: str, journals_without_verdict: Sequence[str], lock_open_by: Sequence[str]
) -> bool:
    """The box's word that a run stopped and will not end: its journal is left
    without a verdict and nobody holds the box's lock. The one rule of
    ``abandoned`` here and of the expiry of a command whose run died
    (``app.agent.queue``, DM-196)."""
    return run_id in journals_without_verdict and not lock_open_by


def run_status(
    *,
    run_id: str,
    ended: bool,
    heartbeat_at: datetime | None,
    journals_without_verdict: Sequence[str],
    lock_open_by: Sequence[str],
    now: datetime,
) -> RunStatus:
    if ended:
        return RunStatus.FINISHED
    if heartbeat_at is None or now - heartbeat_at > HEARTBEAT_SILENCE:
        return RunStatus.SILENT
    if dead(run_id, journals_without_verdict, lock_open_by):
        return RunStatus.ABANDONED
    return RunStatus.RUNNING
