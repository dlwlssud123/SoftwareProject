"""Remove expired usage metadata; no user content or service records are affected."""

import json

from sqlalchemy.orm import Session

from app.api.usage import prune
from app.core.database import engine


def main():
    with Session(engine) as db:
        removed = prune(db)
        db.commit()
    print(json.dumps({"removed": removed, "retention_days": 30}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
