import uuid
import logging
from datetime import datetime, timezone
from typing import List
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.reservation import Reservation, ReservationStatus
from app.models.user import User
from app.core.exceptions import NotFoundException

logger = logging.getLogger("notifications")


class NotificationService:
    @staticmethod
    def create_reservation_accepted_notification(
        db: Session,
        reservation: Reservation,
    ) -> Notification:
        """Creates a notification when a reservation is accepted/confirmed."""
        branch_name = reservation.branch.name if reservation.branch else "Sucursal"
        title = "¡Tu pedido fue aceptado!"
        message = (
            f"Tu pedido {reservation.reservation_code} fue aceptado. "
            f"Ya puedes pasar por la sucursal {branch_name} a probarte o retirar tus prendas."
        )

        existing = (
            db.query(Notification)
            .filter(
                Notification.user_id == reservation.customer_id,
                Notification.reservation_id == reservation.id,
                Notification.notification_type == "RESERVATION_ACCEPTED",
            )
            .first()
        )
        if existing:
            return existing

        notif = Notification(
            id=str(uuid.uuid4()),
            user_id=reservation.customer_id,
            reservation_id=reservation.id,
            title=title,
            message=message,
            notification_type="RESERVATION_ACCEPTED",
            is_read=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)
        return notif

    @staticmethod
    def list_user_notifications(db: Session, user: User) -> List[Notification]:
        """Lists notifications for a user, auto-syncing confirmed reservations."""
        # Auto-sync confirmed/paid reservations of this customer that don't have a notification yet
        confirmed_res = (
            db.query(Reservation)
            .filter(
                Reservation.customer_id == user.id,
                Reservation.status.in_([
                    ReservationStatus.CONFIRMED.value,
                    ReservationStatus.COMPLETED.value,
                ]),
            )
            .all()
        )

        for r in confirmed_res:
            existing = (
                db.query(Notification)
                .filter(
                    Notification.user_id == user.id,
                    Notification.reservation_id == r.id,
                )
                .first()
            )
            if not existing:
                try:
                    NotificationService.create_reservation_accepted_notification(db, r)
                except Exception as e:
                    logger.warning(f"Error auto-creando notificación para reserva {r.id}: {e}")

        return (
            db.query(Notification)
            .filter(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(50)
            .all()
        )

    @staticmethod
    def get_unread_count(db: Session, user: User) -> int:
        """Returns the number of unread notifications."""
        # Run sync first to ensure up-to-date count
        NotificationService.list_user_notifications(db, user)
        return (
            db.query(Notification)
            .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
            .count()
        )

    @staticmethod
    def mark_as_read(db: Session, user: User, notification_id: str) -> Notification:
        notif = (
            db.query(Notification)
            .filter(Notification.id == notification_id, Notification.user_id == user.id)
            .first()
        )
        if not notif:
            raise NotFoundException(detail="Notificación no encontrada")

        notif.is_read = True
        db.commit()
        db.refresh(notif)
        return notif

    @staticmethod
    def mark_all_as_read(db: Session, user: User) -> int:
        count = (
            db.query(Notification)
            .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
            .update({"is_read": True}, synchronize_session=False)
        )
        db.commit()
        return count
