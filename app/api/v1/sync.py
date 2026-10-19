"""Authenticated, idempotent outbox commands; no arbitrary HTTP replay."""
import hashlib
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.cart_item import CartItem
from app.models.sync_operation import SyncOperation
from app.schemas.cart import CartItemAdd, CartItemUpdate
from app.schemas.reservation import ReservationCreate, PayPalCaptureRequest
from app.schemas.user import UserUpdate, UserResponse
from app.services.cart_service import CartService
from app.services.reservation_service import ReservationService
from app.services.user_service import UserService
from app.schemas.virtual_fitting import BiometricProfileCreate, BiometricProfileResponse
from app.services.virtual_fitting_service import VirtualFittingService
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/sync", tags=["Offline synchronization"])


class SyncCommand(BaseModel):
    operation_id: uuid.UUID
    account_id: str | None = Field(default=None, max_length=36)
    method: str = Field(pattern="^(POST|PUT|DELETE|PATCH)$")
    path: str = Field(max_length=200)
    body: dict = Field(default_factory=dict)


def dispatch(db, user, command):
    path, method, body = command.path, command.method, command.body.copy()
    if path == "/virtual-fitting/profile" and method == "POST":
        return BiometricProfileResponse.model_validate(VirtualFittingService.upsert_profile(db,user.id,BiometricProfileCreate.model_validate(body)))
    if path == "/notifications/read-all" and method == "PATCH":
        return {"count":NotificationService.mark_all_as_read(db,user)}
    if path.startswith("/notifications/") and path.endswith("/read") and method == "PATCH":
        result = NotificationService.mark_as_read(db,user,path.split("/")[-2])
        return {"id":result.id,"is_read":True}
    if path == "/reservations/paypal-capture" and method == "POST":
        request = PayPalCaptureRequest.model_validate(body)
        return ReservationService.capture_paypal_order(db, user, request.paypal_order_id)
    if path == "/reservations" and method == "POST":
        # An offline PayPal intent reserves stock, but does not charge money.
        data = ReservationCreate.model_validate(body)
        return ReservationService.create_reservation(db, user, data)
    if path.startswith("/reservations/") and method == "DELETE":
        return ReservationService.cancel_by_customer(db, path.split("/")[-1], user)
    if path == "/users/me" and method == "PUT":
        return UserResponse.model_validate(UserService.update(db, user, UserUpdate.model_validate(body)))
    if path == "/cart/items" and method == "POST":
        return CartService.add_item(db, user.id, CartItemAdd.model_validate(body))
    if path == "/cart" and method == "DELETE":
        return CartService.clear_cart(db, user.id)
    if path.startswith("/cart/items/") and method in ("PUT", "DELETE"):
        variant_id = body.pop("_variant_id", None)
        item = db.query(CartItem).filter(CartItem.user_id == user.id)
        item = item.filter(CartItem.variant_id == variant_id) if variant_id else item.filter(CartItem.id == path.split("/")[-1])
        item = item.first()
        if not item:
            if method == "DELETE":
                return CartService.get_cart(db, user.id)
            raise HTTPException(409, "La prenda ya no está en tu carrito. Revisa los cambios pendientes.")
        if method == "PUT":
            return CartService.update_item_quantity(db, user.id, item.id, CartItemUpdate.model_validate(body))
        return CartService.remove_item(db, user.id, item.id)
    raise HTTPException(422, "Esta acción requiere conexión y no admite sincronización diferida.")


@router.post("/operations")
def apply_operation(command: SyncCommand, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if command.account_id is not None and command.account_id != user.id:
        raise HTTPException(403, "Esta operación pertenece a otra cuenta. Inicia sesión con su cuenta original.")
    fingerprint = hashlib.sha256(json.dumps(command.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    # Serializes retries for one account across processes in PostgreSQL.
    db.query(User).filter(User.id == user.id).with_for_update().first()
    receipt = db.query(SyncOperation).filter_by(user_id=user.id, operation_id=str(command.operation_id)).first()
    if receipt:
        if receipt.fingerprint != fingerprint:
            raise HTTPException(409, "La misma operación no puede reutilizarse con otros datos.")
        return json.loads(receipt.response)
    db.info["sync_atomic"] = True
    try:
        result = jsonable_encoder(dispatch(db, user, command))
        db.add(SyncOperation(id=str(uuid.uuid4()), user_id=user.id,
                             operation_id=str(command.operation_id), fingerprint=fingerprint,
                             response=json.dumps(result)))
        db.commit()
        return result
    except ValidationError as error:
        db.rollback()
        raise HTTPException(422, "Datos de la operación inválidos: " + str(error)) from error
    except OperationalError as error:
        db.rollback()
        raise HTTPException(503, "La operación está ocupada. Se reintentará con el mismo identificador.") from error
    except Exception:
        db.rollback()
        raise
    finally:
        db.info.pop("sync_atomic", None)
