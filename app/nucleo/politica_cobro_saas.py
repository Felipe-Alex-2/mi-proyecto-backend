"""Fixed billing terms; safe to apply repeatedly without altering paid receipts."""
from sqlalchemy import update
from app.modelos.saas import Plan, Suscripcion, PRO_PRICE_USD, PRO_DURATION_DAYS


def ensure_billing_policy(conn):
    conn.execute(update(Plan).where(Plan.code == 'BASIC').values(price_usd=0, duration_days=0))
    conn.execute(update(Plan).where(Plan.code == 'PRO').values(price_usd=PRO_PRICE_USD, duration_days=PRO_DURATION_DAYS))
    conn.execute(update(Suscripcion).where(Suscripcion.plan_code == 'BASIC').values(expires_at=None))
