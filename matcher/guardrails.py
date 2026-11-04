"""Checks that run after matching. If any fail, no output is written.

These exist because a confident wrong answer is worse than no answer when
money is involved. Every check adds up rows itself rather than trusting a
pre-computed total.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Iterable

from .models import Invoice, MatchResult, Payment

ZERO = Decimal("0.00")


class GuardrailError(Exception):
    pass


def verify(result: MatchResult, invoices: Iterable[Invoice], payments: Iterable[Payment]) -> list[str]:
    """Raise GuardrailError on any failure. Returns the list of checks that passed."""
    invoices = {i.invoice_id: i for i in invoices}
    payments = list(payments)
    passed: list[str] = []
    failures: list[str] = []

    # 1. Every active payment is fully accounted for: applied + sent to review == received.
    applied = defaultdict(lambda: ZERO)
    for a in result.applications:
        applied[a.payment_id] += a.amount
    reviewed = defaultdict(lambda: ZERO)
    for r in result.review_queue:
        reviewed[r.payment_id] += r.unapplied_amount
    for p in payments:
        if p.is_void:
            continue
        if applied[p.payment_id] + reviewed[p.payment_id] != p.amount:
            failures.append(
                f"{p.payment_id}: applied {applied[p.payment_id]} + review "
                f"{reviewed[p.payment_id]} does not equal payment {p.amount}")
    if not failures:
        passed.append("Every dollar of every payment is either applied or in the review queue")

    # 2. No invoice receives more than it was owed.
    per_invoice = defaultdict(lambda: ZERO)
    for a in result.applications:
        per_invoice[a.invoice_id] += a.amount
    over = [i for i, amt in per_invoice.items() if amt > invoices[i].amount_due]
    failures += [f"{i} over-applied" for i in over]
    if not over:
        passed.append("No invoice is over-applied")

    # 3. Cash only goes to the customer who sent it.
    pay_customer = {p.payment_id: p.customer_id for p in payments}
    wrong = [a for a in result.applications
             if invoices[a.invoice_id].customer_id != pay_customer[a.payment_id]]
    failures += [f"{a.payment_id} applied to another customer's invoice {a.invoice_id}" for a in wrong]
    if not wrong:
        passed.append("No payment is applied to another customer's invoice")

    # 4. Voided payments never appear in the output.
    void_ids = {p.payment_id for p in payments if p.is_void}
    leaked = {a.payment_id for a in result.applications} & void_ids
    failures += [f"Voided payment {pid} was applied" for pid in sorted(leaked)]
    if not leaked:
        passed.append("No voided payment is applied")

    # 5. No zero or negative rows.
    bad_rows = [a for a in result.applications if a.amount <= ZERO]
    failures += [f"Non-positive application row on {a.invoice_id}" for a in bad_rows]
    if not bad_rows:
        passed.append("Every application row is a positive amount")

    if failures:
        raise GuardrailError("Guardrail checks failed:\n  " + "\n  ".join(failures))
    return passed
