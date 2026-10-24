from sqlalchemy.orm import Session


def commit_or_flush(db: Session):
    """Sync commands and their receipt must commit in the same transaction."""
    if db.info.get("sync_atomic"):
        db.flush()
    else:
        db.commit()
