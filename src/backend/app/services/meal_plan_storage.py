from sqlalchemy import select

from app.core.auth import unauthenticated
from app.models import User


def lock_plan_owner(db, user_id, *, read=False):
    """Serialize plan edits and purchase checks, including insertion of a new meal slot."""
    if (
        db.scalar(select(User.id).where(User.id == user_id).with_for_update(read=read))
        is None
    ):
        raise unauthenticated()
