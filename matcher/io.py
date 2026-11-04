"""Read input CSVs and write the upload template, review queue and summary."""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import Invoice, MatchResult, Payment, Remittance

ZERO = Decimal("0.00")


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_invoices(path: Path) -> list[Invoice]:
    return [Invoice(r["invoice_id"], r["customer_id"], r["facility"],
                    Decimal(r["amount_due"]), date.fromisoformat(r["due_date"]))
            for r in _rows(path)]


def load_payments(path: Path) -> list[Payment]:
    return [Payment(r["payment_id"], r["customer_id"], Decimal(r["amount"]),
                    date.fromisoformat(r["received_date"]), r.get("reference", ""),
                    r.get("status", "POSTED"))
            for r in _rows(path)]


def load_remittances(path: Path) -> list[Remittance]:
    if not path.exists():
        return []
    return [Remittance(r["payment_id"],
                       tuple(i.strip() for i in r.get("invoice_ids", "").split(";") if i.strip()),
                       r.get("instruction", "").strip())
            for r in _rows(path)]


def write_outputs(result: MatchResult, payments: list[Payment], checks: list[str], out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "application_template.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["payment_id", "invoice_id", "amount", "method", "confidence", "requires_approval"])
        for a in result.applications:
            w.writerow([a.payment_id, a.invoice_id, f"{a.amount:.2f}", a.method, a.confidence,
                        "YES" if a.requires_approval else "NO"])

    with open(out / "review_queue.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["payment_id", "customer_id", "unapplied_amount", "category", "reason"])
        for r in result.review_queue:
            w.writerow([r.payment_id, r.customer_id, f"{r.unapplied_amount:.2f}", r.category, r.reason])

    summary = build_summary(result, payments, checks)
    (out / "summary.md").write_text(summary, encoding="utf-8")
    return summary


def build_summary(result: MatchResult, payments: list[Payment], checks: list[str]) -> str:
    active = [p for p in payments if not p.is_void]
    received = sum((p.amount for p in active), ZERO)
    applied = sum((a.amount for a in result.applications), ZERO)
    in_review = sum((r.unapplied_amount for r in result.review_queue), ZERO)

    by_conf = defaultdict(lambda: ZERO)
    for a in result.applications:
        by_conf[a.confidence] += a.amount

    reason_counts = Counter(r.category for r in result.review_queue)
    reason_amounts = defaultdict(lambda: ZERO)
    for r in result.review_queue:
        reason_amounts[r.category] += r.unapplied_amount

    pct = lambda x: f"{(x / received * 100):.0f}%" if received else "0%"
    lines = [
        "# Payment matching summary",
        "",
        f"- Payments processed: {len(active)} (plus {len(result.skipped_void)} voided, skipped)",
        f"- Cash received: ${received:,.2f}",
        f"- Applied: ${applied:,.2f} ({pct(applied)})",
        f"- Sent to review: ${in_review:,.2f} ({pct(in_review)})",
        "",
        "## Applied, by confidence",
        "",
        "| Confidence | Amount | Needs approval |",
        "|---|---|---|",
    ]
    for conf in ("HIGH", "MEDIUM", "LOW"):
        lines.append(f"| {conf} | ${by_conf[conf]:,.2f} | {'No' if conf == 'HIGH' else 'Yes'} |")
    lines += ["", "## Review queue, by reason", "", "| Reason | Payments | Amount |", "|---|---|---|"]
    for reason, n in reason_counts.most_common():
        lines.append(f"| {reason} | {n} | ${reason_amounts[reason]:,.2f} |")
    lines += ["", "## Guardrail checks", ""]
    lines += [f"- PASS: {c}" for c in checks]
    return "\n".join(lines) + "\n"
