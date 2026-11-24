"""Writing the audit trail: one function, rows only added.

The row goes into the caller's session -- the transaction of the action it
records: an action rolled back leaves no row, a row is never without its
action. ``details`` never carries the value of a secret.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import ActorKind, Audit


def record(
    session: AsyncSession,
    *,
    actor_kind: ActorKind,
    actor_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    action: str,
    object_kind: str,
    object_id: str,
    details: dict[str, object] | None = None,
    result: str = "ok",
) -> None:
    """Add one row of the audit trail to ``session``."""
    session.add(
        Audit(
            actor_kind=actor_kind.value,
            actor_id=actor_id,
            project_id=project_id,
            action=action,
            object_kind=object_kind,
            object_id=object_id,
            result=result,
            details=details or {},
        )
    )
