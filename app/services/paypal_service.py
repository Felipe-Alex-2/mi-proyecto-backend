"""
PayPal REST API client — Sandbox y Producción.
Maneja autenticación OAuth2 y ciclo de vida de órdenes v2.
"""
import base64
import logging
from typing import Any, Dict, Optional
import httpx
from app.config import settings

logger = logging.getLogger("paypal")


class PayPalService:
    """Helper stateless para comunicarse con PayPal REST API."""

    @staticmethod
    def _get_access_token() -> str:
        credentials = f"{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_CLIENT_SECRET}"
        encoded = base64.b64encode(credentials.encode()).decode()

        response = httpx.post(
            f"{settings.PAYPAL_BASE_URL}/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
            timeout=30.0,
        )

        if response.status_code != 200:
            logger.error(f"PayPal OAuth falló: {response.status_code} — {response.text}")
            raise Exception(f"Fallo de autenticación con PayPal: {response.text}")

        return response.json()["access_token"]

    @staticmethod
    def create_order(
        amount: float,
        currency: Optional[str] = None,
        description: str = "Pago de Reserva de Prendas",
        return_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        custom_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        access_token = PayPalService._get_access_token()
        curr = currency or settings.PAYPAL_CURRENCY or "EUR"
        ret_url = return_url or "https://www.sandbox.paypal.com/myaccount/summary?intl=0"
        canc_url = cancel_url or "https://www.sandbox.paypal.com/myaccount/summary?intl=0"

        # Sanitizar descripción a caracteres ASCII puros para evitar errores 400 de PayPal
        clean_desc = (description or "Pago de Reserva").encode("ascii", "ignore").decode("ascii").strip()
        if not clean_desc:
            clean_desc = "Pago de Reserva"

        purchase_unit = {
            "amount": {
                "currency_code": curr,
                "value": f"{amount:.2f}",
            },
            "description": clean_desc[:127],
        }
        if custom_id:
            purchase_unit["custom_id"] = str(custom_id)[:127]

        order_payload = {
            "intent": "CAPTURE",
            "purchase_units": [purchase_unit],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "brand_name": "FashionStore",
                        "landing_page": "LOGIN",
                        "user_action": "PAY_NOW",
                        "shipping_preference": "NO_SHIPPING",
                        "return_url": ret_url,
                        "cancel_url": canc_url,
                    }
                }
            },
        }

        response = httpx.post(
            f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=order_payload,
            timeout=30.0,
        )

        if response.status_code not in (200, 201):
            logger.error(f"Error creando orden PayPal: {response.status_code} — {response.text}")
            raise Exception(f"Error al crear orden en PayPal: {response.text}")

        data = response.json()
        order_id = data["id"]

        # Extraer enlace de aprobación
        approval_url: Optional[str] = None
        for link in data.get("links", []):
            if link.get("rel") in ("payer-action", "approve"):
                approval_url = link.get("href")
                break

        if not approval_url:
            approval_url = f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}"

        if "fundingSource=" not in approval_url:
            separator = "&" if "?" in approval_url else "?"
            approval_url = f"{approval_url}{separator}fundingSource=paypal"

        return {
            "order_id": order_id,
            "id": order_id,
            "approval_url": approval_url,
        }

    @staticmethod
    def capture_order(order_id: str) -> Dict[str, Any]:
        access_token = PayPalService._get_access_token()

        response = httpx.post(
            f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders/{order_id}/capture",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

        if response.status_code not in (200, 201):
            logger.error(f"Error capturando PayPal {order_id}: {response.status_code} — {response.text}")
            raise Exception(f"Error al capturar orden PayPal: {response.text}")

        data = response.json()
        status = data.get("status", "UNKNOWN")

        capture_id: Optional[str] = None
        purchase_units = data.get("purchase_units", [])
        if purchase_units:
            captures = purchase_units[0].get("payments", {}).get("captures", [])
            if captures:
                capture_id = captures[0].get("id")

        return {
            "order_id": order_id,
            "capture_id": capture_id,
            "status": status,
            "raw": data,
        }

    @staticmethod
    def get_order(order_id: str) -> Dict[str, Any]:
        """Consulta el estado actual de una orden en PayPal Sandbox / Live."""
        try:
            access_token = PayPalService._get_access_token()
            response = httpx.get(
                f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders/{order_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=20.0,
            )
            if response.status_code != 200:
                logger.warning(f"No se pudo consultar orden PayPal {order_id}: {response.status_code}")
                return {"status": "UNKNOWN"}
            return response.json()
        except Exception as e:
            logger.error(f"Error consultando orden PayPal {order_id}: {str(e)}")
            return {"status": "UNKNOWN"}

