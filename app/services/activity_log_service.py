from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.activity_log import ActivityLog
from app.models.user import User
from app.schemas.activity_log import ActivityLogCreate, ActivityLogListResponse


class ActivityLogService:
    @staticmethod
    def create(
        db: Session,
        user: User,
        payload: ActivityLogCreate,
        request: Optional[Request] = None,
    ) -> ActivityLog:
        forwarded_for = request.headers.get("x-forwarded-for") if request else None
        ip_address = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request and request.client else None)
        log = ActivityLog(
            user_id=user.id,
            user_email=user.email,
            user_name=user.full_name,
            action=payload.action.strip().upper(),
            description=payload.description.strip(),
            category=payload.category.strip().upper(),
            ip_address=ip_address,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    @staticmethod
    def log_event(
        db: Session,
        user: Optional[User],
        action: str,
        description: str,
        category: str = "NEGOCIO",
        ip_address: Optional[str] = None,
    ) -> Optional[ActivityLog]:
        try:
            log = ActivityLog(
                user_id=user.id if user else None,
                user_email=user.email if user else "sistema@local.dev",
                user_name=user.full_name if user else "Sistema",
                action=action.strip().upper(),
                description=description.strip(),
                category=category.strip().upper(),
                ip_address=ip_address,
            )
            db.add(log)
            db.commit()
            db.refresh(log)
            return log
        except Exception:
            db.rollback()
            return None

    @staticmethod
    def list_logs(
        db: Session,
        page: int = 1,
        page_size: int = 25,
        action: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
    ) -> ActivityLogListResponse:
        query = db.query(ActivityLog)
        if action:
            query = query.filter(ActivityLog.action == action.strip().upper())
        if category:
            query = query.filter(ActivityLog.category == category.strip().upper())
        if search:
            term = f"%{search.strip()}%"
            query = query.filter(
                (ActivityLog.user_name.ilike(term))
                | (ActivityLog.user_email.ilike(term))
                | (ActivityLog.description.ilike(term))
            )

        total = query.count()
        items = (
            query.order_by(ActivityLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return ActivityLogListResponse(items=items, total=total, page=page, page_size=page_size)
