"""Operator-only admin accounts. Read passwords interactively, never from arguments."""

import argparse
import getpass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.passwords import hash_password, normalize_username
from app.models import AdminCredential, AuthSession, User


def _lock(db, username):
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended("valueflow-admin:" + username, 0)
            )
        )
    )
    return db.execute(
        select(AdminCredential, User)
        .join(User, User.id == AdminCredential.user_id)
        .where(AdminCredential.username == username)
        .with_for_update(of=(AdminCredential, User))
    ).one_or_none()


def provision(db: Session, username: str, password: str, *, replace: bool = False):
    username = normalize_username(username)
    encoded = hash_password(password)
    try:
        row = _lock(db, username)
        now = datetime.now(UTC)
        if row is None:
            if replace:
                raise ValueError("Admin account does not exist")
            user = User(role="admin")
            db.add(user)
            db.flush()
            credential = AdminCredential(
                username=username, user_id=user.id, password_hash=encoded
            )
            db.add(credential)
        else:
            credential, user = row
            if not replace:
                raise ValueError("Account exists; use --reset-password explicitly")
            if user.role != "admin" or user.disabled_at is not None:
                raise ValueError(
                    "An active admin identity is required; roles are not changed by this command"
                )
            credential.password_hash = encoded
            credential.enabled = True
            credential.failed_attempts = 0
            credential.locked_until = None
            credential.updated_at = now
            db.execute(
                update(AuthSession)
                .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=now)
            )
        db.commit()
        return user.id
    except Exception:
        db.rollback()
        raise


def disable(db: Session, username: str):
    try:
        row = _lock(db, normalize_username(username))
        if row is None:
            raise ValueError("Admin account does not exist")
        credential, user = row
        now = datetime.now(UTC)
        credential.enabled = False
        credential.updated_at = now
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="서버 운영자 전용 관리자 계정 관리")
    parser.add_argument("username", type=normalize_username)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--reset-password", action="store_true")
    modes.add_argument("--disable", action="store_true")
    args = parser.parse_args(argv)
    from app.core.database import SessionLocal

    try:
        with SessionLocal() as db:
            if args.disable:
                disable(db, args.username)
            else:
                password = getpass.getpass("비밀번호 (15~128자): ")
                confirmation = getpass.getpass("비밀번호 확인: ")
                if password != confirmation:
                    raise ValueError("Passwords do not match")
                provision(db, args.username, password, replace=args.reset_password)
    except (ValueError, EOFError) as error:
        parser.exit(1, f"{error}\n")
    except SQLAlchemyError:
        parser.exit(
            1, "관리자 계정 DB 작업에 실패했습니다. 연결과 마이그레이션을 확인하세요.\n"
        )
    print("관리자 계정 처리가 완료됐습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
