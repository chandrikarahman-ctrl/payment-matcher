"""Core matching logic.

Each payment goes down a ladder of strategies, from most to least trustworthy.
The first strategy that produces a single, unambiguous answer wins. If a
strategy finds more than one plausible answer, the payment goes to the review
queue instead of falling through to a weaker strategy. Guessing is never
allowed.

    1. Remittance lists invoices        -> HIGH confidence
    2. Remittance says "oldest first"   -> HIGH confidence
    3. Invoice number in payment memo   -> MEDIUM confidence
    4. Exactly one invoice matches amount -> MEDIUM confidence
    5. Exactly one combination of invoices sums to amount -> LOW confidence
    6. Otherwise                        -> review queue
"""
from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal
from itertools import combinations
from typing import Iterable

from .models import Application, Invoice, MatchResult, Payment, Remittance, ReviewItem

INVOICE_ID_PATTERN = re.compile(r"\bINV-\d{5}\b", re.IGNORECASE)
ZERO = Decimal("0.00")


class Matcher:
    def __init__(
        self,
        invoices: Iterable[Invoice],
        max_combo_size: int = 4,
        max_combo_candidates: int = 15,
    ) -> None:
        self.invoices = {inv.invoice_id: inv for inv in invoices}
        self.remaining = {inv.invoice_id: inv.amount_due for inv in self.invoices.values()}
        self.max_combo_size = max_combo_size
        self.max_combo_candidates = max_combo_candidates

    # ------------------------------------------------------------------ helpers
    def _open_invoices(self, customer_id: str) -> list[Invoice]:
        return sorted(
            (inv for inv in self.invoices.values()
             if inv.customer_id == customer_id and self.remaining[inv.invoice_id] > ZERO),
            key=lambda inv: (inv.due_date, inv.invoice_id),
        )

    def _apply(self, result: MatchResult, payment: Payment, invoice_id: str,
               amount: Decimal, method: str, confidence: str) -> None:
        if amount <= ZERO:
            return
        if amount > self.remaining[invoice_id]:
            # Never over-apply. This should be impossible; fail loudly if it is not.
            raise ValueError(f"Over-application blocked on {invoice_id}")
        self.remaining[invoice_id] -= amount
        result.applications.append(
            Application(payment.payment_id, invoice_id, amount, method, confidence)
        )

    @staticmethod
    def _review(result: MatchResult, payment: Payment, amount: Decimal,
                category: str, reason: str) -> None:
        if amount > ZERO:
            result.review_queue.append(
                ReviewItem(payment.payment_id, payment.customer_id, amount, category, reason)
            )

    # --------------------------------------------------------------- strategies
    def _apply_listed(self, result: MatchResult, payment: Payment, invoice_ids: list[str],
                      method: str, confidence: str) -> None:
        """Apply a payment to a specific list of invoices, after validating every one."""
        problems = []
        for inv_id in invoice_ids:
            inv = self.invoices.get(inv_id)
            if inv is None:
                problems.append(f"{inv_id} not found")
            elif inv.customer_id != payment.customer_id:
                problems.append(f"{inv_id} belongs to a different customer")
            elif self.remaining[inv_id] <= ZERO:
                problems.append(f"{inv_id} is already paid")
        if problems:
            # One bad invoice makes the whole instruction suspect. Do not partially apply.
            self._review(result, payment, payment.amount, "Invalid invoice reference",
                         f"{method}: invoice list failed validation ({'; '.join(problems)})")
            return

        listed_total = sum((self.remaining[i] for i in invoice_ids), ZERO)
        if payment.amount < listed_total:
            self._review(result, payment, payment.amount, "Short payment",
                         f"Short payment: {method} lists ${listed_total:,.2f} but payment is "
                         f"${payment.amount:,.2f}. Needs a decision on which invoice is short.")
            return

        for inv_id in invoice_ids:
            self._apply(result, payment, inv_id, self.remaining[inv_id], method, confidence)
        leftover = payment.amount - listed_total
        self._review(result, payment, leftover, "Overpayment",
                     f"Overpayment: ${leftover:,.2f} left after paying all listed invoices")

    def _apply_oldest_first(self, result: MatchResult, payment: Payment) -> None:
        left = payment.amount
        for inv in self._open_invoices(payment.customer_id):
            if left <= ZERO:
                break
            amount = min(left, self.remaining[inv.invoice_id])
            self._apply(result, payment, inv.invoice_id, amount,
                        "Remittance: oldest first", "HIGH")
            left -= amount
        self._review(result, payment, left, "Overpayment",
                     f"Overpayment: ${left:,.2f} left after paying all open invoices oldest first")

    def _match_by_amount(self, result: MatchResult, payment: Payment) -> bool:
        """Returns True if the payment was handled (applied or sent to review)."""
        open_invs = self._open_invoices(payment.customer_id)

        exact = [inv for inv in open_invs if self.remaining[inv.invoice_id] == payment.amount]
        if len(exact) == 1:
            self._apply(result, payment, exact[0].invoice_id, payment.amount,
                        "Exact amount match", "MEDIUM")
            return True
        if len(exact) > 1:
            self._review(result, payment, payment.amount, "Ambiguous match",
                         f"Ambiguous: {len(exact)} open invoices have exactly this amount")
            return True

        if len(open_invs) > self.max_combo_candidates:
            self._review(result, payment, payment.amount, "Too many candidates",
                         f"No remittance, and {len(open_invs)} open invoices is too many to "
                         "search safely for a combination")
            return True

        solutions = []
        for size in range(2, self.max_combo_size + 1):
            for combo in combinations(open_invs, size):
                if sum((self.remaining[i.invoice_id] for i in combo), ZERO) == payment.amount:
                    solutions.append(combo)
                    if len(solutions) > 1:
                        break
            if len(solutions) > 1:
                break

        if len(solutions) == 1:
            for inv in solutions[0]:
                self._apply(result, payment, inv.invoice_id, self.remaining[inv.invoice_id],
                            "Invoice combination match", "LOW")
            return True
        if len(solutions) > 1:
            self._review(result, payment, payment.amount, "Ambiguous match",
                         "Ambiguous: more than one combination of invoices adds up to this amount")
            return True
        return False

    # --------------------------------------------------------------------- run
    def run(self, payments: Iterable[Payment],
            remittances: Iterable[Remittance] = ()) -> MatchResult:
        result = MatchResult()
        remit_by_payment: dict[str, Remittance] = {r.payment_id: r for r in remittances}

        # Oldest cash first, so earlier payments claim invoices before later ones.
        for payment in sorted(payments, key=lambda p: (p.received_date, p.payment_id)):
            if payment.is_void:
                result.skipped_void.append(payment)
                continue

            remit = remit_by_payment.get(payment.payment_id)
            if remit and remit.instruction.upper() == "OLDEST_FIRST":
                self._apply_oldest_first(result, payment)
                continue
            if remit and remit.invoice_ids:
                self._apply_listed(result, payment, list(remit.invoice_ids),
                                   "Remittance", "HIGH")
                continue

            memo_ids = list(dict.fromkeys(m.upper() for m in INVOICE_ID_PATTERN.findall(payment.reference)))
            if memo_ids:
                self._apply_listed(result, payment, memo_ids, "Payment memo", "MEDIUM")
                continue

            if self._match_by_amount(result, payment):
                continue

            self._review(result, payment, payment.amount, "No information",
                         "No remittance, no invoice number, and no confident amount match")
        return result


def by_customer(applications: Iterable[Application], invoices: dict[str, Invoice]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for app in applications:
        totals[invoices[app.invoice_id].customer_id] += app.amount
    return dict(totals)
