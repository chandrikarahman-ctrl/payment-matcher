"""Data models for the payment matcher.

All money is handled as Decimal so totals never drift from floating point error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    customer_id: str
    facility: str
    amount_due: Decimal
    due_date: date


@dataclass(frozen=True)
class Payment:
    payment_id: str
    customer_id: str
    amount: Decimal
    received_date: date
    reference: str = ""
    status: str = "POSTED"  # POSTED or VOID

    @property
    def is_void(self) -> bool:
        return self.status.upper() == "VOID"


@dataclass(frozen=True)
class Remittance:
    """Remittance advice sent by the customer, usually by email."""
    payment_id: str
    invoice_ids: tuple[str, ...] = ()
    instruction: str = ""  # e.g. "OLDEST_FIRST"


@dataclass(frozen=True)
class Application:
    """One row in the upload template: apply this much of a payment to this invoice."""
    payment_id: str
    invoice_id: str
    amount: Decimal
    method: str
    confidence: str  # HIGH, MEDIUM, LOW

    @property
    def requires_approval(self) -> bool:
        return self.confidence != "HIGH"


@dataclass(frozen=True)
class ReviewItem:
    """Cash the tool will not apply on its own, with the reason why."""
    payment_id: str
    customer_id: str
    unapplied_amount: Decimal
    category: str
    reason: str


@dataclass
class MatchResult:
    applications: list[Application] = field(default_factory=list)
    review_queue: list[ReviewItem] = field(default_factory=list)
    skipped_void: list[Payment] = field(default_factory=list)
