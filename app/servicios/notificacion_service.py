from app.nucleo.transacciones import commit_or_flush
import uuid
import logging
from datetime import datetime, timezone
from typing import List
from sqlalchemy.orm import Session

from app.modelos.notificacion import Notificacion
from app.modelos.reserva import Reserva, EstadoReserva
from app.modelos.usuario import Usuario
from app.nucleo.excepciones import NoEncontradoException

logger = logging.getLogger("notifications")


class NotificacionService:
    @staticmethod
    def create_reservation_accepted_notification(
        db: Session,
        reservation: Reserva,
    ) -> Notificacion:
        """Creates a notification when a reservation is accepted/confirmed."""
        branch_name = reservation.branch.name if reservation.branch else "Sucursal"
        title = "¡Tu pedido fue aceptado!"
        message = (
            f"Tu pedido {reservation.reservation_code} fue aceptado. "
            f"Ya puedes pasar por la sucursal {branch_name} a probarte o retirar tus prendas."
        )

        existing = (
            db.query(Notificacion)
            .filter(
                Notificacion.user_id == reservation.customer_id,
                Notificacion.reservation_id == reservation.id,
                Notificacion.notification_type == "RESERVATION_ACCEPTED",
            )
            .first()
        )
        if existing:
            return existing

        notif = Notificacion(
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
        commit_or_flush(db)
        db.refresh(notif)
        return notif

    @staticmethod
    def list_user_notifications(db: Session, user: Usuario) -> List[Notificacion]:
        """Lists notifications for a user, auto-syncing confirmed reservations."""
        # Auto-sync confirmed/paid reservations of this customer that don't have a notification yet
        confirmed_res = (
            db.query(Reserva)
            .filter(
                Reserva.customer_id == user.id,
                Reserva.status.in_([
                    EstadoReserva.CONFIRMED.value,
                    EstadoReserva.COMPLETED.value,
                ]),
            )
            .all()
        )

        for r in confirmed_res:
            existing = (
                db.query(Notificacion)
                .filter(
                    Notificacion.user_id == user.id,
                    Notificacion.reservation_id == r.id,
                )
                .first()
            )
            if not existing:
                try:
                    NotificacionService.create_reservation_accepted_notification(db, r)
                except Exception as e:
                    logger.warning(f"Error auto-creando notificación para reserva {r.id}: {e}")

        return (
            db.query(Notificacion)
            .filter(Notificacion.user_id == user.id)
            .order_by(Notificacion.created_at.desc())
            .limit(50)
            .all()
        )

    @staticmethod
    def get_unread_count(db: Session, user: Usuario) -> int:
        """Returns the number of unread notifications."""
        # Run sync first to ensure up-to-date count
        NotificacionService.list_user_notifications(db, user)
        return (
            db.query(Notificacion)
            .filter(Notificacion.user_id == user.id, Notificacion.is_read.is_(False))
            .count()
        )

    @staticmethod
    def mark_as_read(db: Session, user: Usuario, notification_id: str) -> Notificacion:
        notif = (
            db.query(Notificacion)
            .filter(Notificacion.id == notification_id, Notificacion.user_id == user.id)
            .first()
        )
        if not notif:
            raise NoEncontradoException(detail="Notificación no encontrada")

        notif.is_read = True
        commit_or_flush(db)
        db.refresh(notif)
        return notif

    @staticmethod
    def mark_all_as_read(db: Session, user: Usuario) -> int:
        count = (
            db.query(Notificacion)
            .filter(Notificacion.user_id == user.id, Notificacion.is_read.is_(False))
            .update({"is_read": True}, synchronize_session=False)
        )
        commit_or_flush(db)
        return count
