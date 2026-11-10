"""Simulated payments: refunds for cancelled and rejected orders."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.payments import Payment


def refund_if_paid_online(session: Session, order_id: int) -> Payment | None:
    """Insert a `refunded` payment with the same amount for card and MB WAY orders.

    A refund is a new row, never an edit of the payment. Cash is not refunded online.
    The partial unique index uq_payments_one_refund_per_order makes a second refund
    impossible even if a bug let two cancels past the order lock.
    """
    paid = session.execute(
        select(Payment).where(
            Payment.order_id == order_id, Payment.status == "approved"
        )
    ).scalar_one_or_none()
    if paid is None or paid.method == "cash":
        return None
    refund = Payment(
        order_id=order_id,
        amount=paid.amount,
        method=paid.method,
        status="refunded",
        # Its own reference: provider_ref is UNIQUE, so it cannot reuse the payment's.
        provider_ref=f"rf_{uuid4().hex}",
    )
    session.add(refund)
    return refund
