from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def log_event(
    db: Session,
    *,
    actor: User,
    entity_type: str,
    entity_id: int,
    action: str,
    field_name: str = "",
    old_value: str = "",
    new_value: str = "",
) -> None:
    db.add(
        AuditLog(
            created_at=datetime.utcnow(),
            actor_id=actor.id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
        )
    )
