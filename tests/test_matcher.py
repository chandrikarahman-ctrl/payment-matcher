"""Unit tests. Run with:  python -m unittest discover tests"""
import unittest
from datetime import date
from decimal import Decimal as D

from matcher import GuardrailError, Invoice, Matcher, Payment, Remittance, verify
from matcher.models import Application, MatchResult


def inv(i, cust="C1", amt="100.00", due="2026-06-01"):
    return Invoice(f"INV-{i}", cust, f"{cust}-F1", D(amt), date.fromisoformat(due))


def pay(i, amt, cust="C1", ref="", status="POSTED", day="2026-09-01"):
    return Payment(f"PAY-{i}", cust, D(amt), date.fromisoformat(day), ref, status)


class MatcherTests(unittest.TestCase):
    def run_and_verify(self, invoices, payments, remits=()):
        result = Matcher(invoices).run(payments, remits)
        verify(result, invoices, payments)  # every test also proves the guardrails hold
        return result

    def test_remittance_list_applies_high_confidence(self):
        invs = [inv(10001), inv(10002, amt="250.00")]
        r = self.run_and_verify(invs, [pay(1, "350.00")],
                                [Remittance("PAY-1", ("INV-10001", "INV-10002"))])
        self.assertEqual(len(r.applications), 2)
        self.assertTrue(all(a.confidence == "HIGH" for a in r.applications))
        self.assertEqual(r.review_queue, [])

    def test_short_payment_goes_to_review_not_partial(self):
        invs = [inv(10001), inv(10002)]
        r = self.run_and_verify(invs, [pay(1, "150.00")],
                                [Remittance("PAY-1", ("INV-10001", "INV-10002"))])
        self.assertEqual(r.applications, [])
        self.assertIn("Short payment", r.review_queue[0].reason)

    def test_wrong_customer_invoice_is_rejected(self):
        invs = [inv(10001, cust="C2")]
        r = self.run_and_verify(invs, [pay(1, "100.00")], [Remittance("PAY-1", ("INV-10001",))])
        self.assertEqual(r.applications, [])
        self.assertIn("different customer", r.review_queue[0].reason)

    def test_overpayment_remainder_goes_to_review(self):
        invs = [inv(10001)]
        r = self.run_and_verify(invs, [pay(1, "130.00")], [Remittance("PAY-1", ("INV-10001",))])
        self.assertEqual(r.applications[0].amount, D("100.00"))
        self.assertEqual(r.review_queue[0].unapplied_amount, D("30.00"))

    def test_oldest_first(self):
        invs = [inv(10002, due="2026-07-01"), inv(10001, due="2026-06-01"), inv(10003, due="2026-08-01")]
        r = self.run_and_verify(invs, [pay(1, "150.00")], [Remittance("PAY-1", (), "OLDEST_FIRST")])
        self.assertEqual([(a.invoice_id, a.amount) for a in r.applications],
                         [("INV-10001", D("100.00")), ("INV-10002", D("50.00"))])

    def test_memo_reference_case_insensitive(self):
        r = self.run_and_verify([inv(10001)], [pay(1, "100.00", ref="paid inv-10001 thanks")])
        self.assertEqual(r.applications[0].method, "Payment memo")

    def test_unique_amount_match(self):
        invs = [inv(10001, amt="100.00"), inv(10002, amt="275.00")]
        r = self.run_and_verify(invs, [pay(1, "275.00")])
        self.assertEqual(r.applications[0].invoice_id, "INV-10002")
        self.assertTrue(r.applications[0].requires_approval)

    def test_duplicate_amounts_are_ambiguous(self):
        invs = [inv(10001), inv(10002)]  # same price, two facilities
        r = self.run_and_verify(invs, [pay(1, "100.00")])
        self.assertEqual(r.applications, [])
        self.assertIn("Ambiguous", r.review_queue[0].reason)

    def test_unique_combination(self):
        invs = [inv(10001, amt="100.00"), inv(10002, amt="250.00"), inv(10003, amt="400.00")]
        r = self.run_and_verify(invs, [pay(1, "500.00")])
        self.assertEqual({a.invoice_id for a in r.applications}, {"INV-10001", "INV-10003"})
        self.assertEqual(r.applications[0].confidence, "LOW")

    def test_void_payment_is_skipped(self):
        r = self.run_and_verify([inv(10001)], [pay(1, "100.00", status="VOID")])
        self.assertEqual(r.applications, [])
        self.assertEqual(len(r.skipped_void), 1)

    def test_earlier_payment_claims_invoice_first(self):
        invs = [inv(10001)]
        r = self.run_and_verify(invs, [pay(2, "100.00", ref="INV-10001", day="2026-09-02"),
                                       pay(1, "100.00", ref="INV-10001", day="2026-09-01")])
        self.assertEqual(r.applications[0].payment_id, "PAY-1")
        self.assertIn("already paid", r.review_queue[0].reason)


class GuardrailTests(unittest.TestCase):
    def test_detects_over_application(self):
        invs = [inv(10001)]
        bad = MatchResult(applications=[Application("PAY-1", "INV-10001", D("150.00"), "x", "HIGH")])
        with self.assertRaises(GuardrailError):
            verify(bad, invs, [pay(1, "150.00")])

    def test_detects_unaccounted_cash(self):
        invs = [inv(10001)]
        bad = MatchResult(applications=[Application("PAY-1", "INV-10001", D("60.00"), "x", "HIGH")])
        with self.assertRaises(GuardrailError):
            verify(bad, invs, [pay(1, "100.00")])


if __name__ == "__main__":
    unittest.main()
