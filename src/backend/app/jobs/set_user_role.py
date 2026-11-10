"""Offline role provisioning with the operator's DB credentials, never an API."""

import argparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import User


def set_role(db: Session, user_id: UUID, role: str) -> None:
    if role not in ("user", "admin"):
        raise ValueError("Role must be user or admin")
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or user.disabled_at is not None:
        raise ValueError("Active user not found")
    user.role = role
    db.commit()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="서버 운영자 전용 사용자 권한 설정")
    parser.add_argument("user_id", type=UUID)
    parser.add_argument("--role", choices=("user", "admin"), required=True)
    args = parser.parse_args(argv)
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        try:
            set_role(db, args.user_id, args.role)
        except ValueError as error:
            parser.exit(1, f"{error}\n")
    print(f"user_id={args.user_id} role={args.role}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
