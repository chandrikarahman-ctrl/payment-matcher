"""Generate a synthetic dataset that mimics the real-world messiness of cash application.

Every customer, facility, invoice and payment here is fictional.

Scenarios are mixed in on purpose, because each one broke something in real life:
  - remittance lists the invoices (the easy case)
  - customer says "apply oldest first"
  - invoice number only in the payment memo
  - no remittance, amount matches one invoice
  - no remittance, amount matches several same-priced invoices (ambiguous)
  - no remittance, amount is a sum of several invoices
  - short payment against a remittance
  - remittance points at another customer's invoice (bad data)
  - voided payment that must not be counted
  - random amount with no information at all

    python data/generate_sample_data.py          # writes CSVs next to this file
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

SEED = 42
OUT = Path(__file__).parent

# Standard subscription tiers. Many facilities share a tier, so many invoices
# share an exact amount. That is what makes amount-only matching dangerous.
TIERS = [Decimal(x) for x in ("1250.00", "1875.00", "2400.00", "3150.00", "4200.00")]
MONTHS = [date(2026, m, 1) for m in (5, 6, 7, 8)]

SCENARIOS = [
    ("remittance_list", 30),
    ("oldest_first", 6),
    ("memo_reference", 14),
    ("exact_amount", 14),
    ("combination", 10),
    ("short_pay", 6),
    ("wrong_customer", 4),
    ("void", 6),
    ("no_info", 6),
]


def build(seed: int = SEED):
    rng = random.Random(seed)
    invoices, payments, remittances = [], [], []
    inv_seq, pay_seq = 10001, 50001
    customers = [f"CUST-{n:03d}" for n in range(1, 31)]

    open_by_customer: dict[str, list[dict]] = {}
    for cust in customers:
        n_fac = rng.randint(2, 5)
        fac_tiers = [rng.choice(TIERS) for _ in range(n_fac)]
        open_by_customer[cust] = []
        for f_idx, tier in enumerate(fac_tiers, start=1):
            for month in MONTHS:
                inv = {
                    "invoice_id": f"INV-{inv_seq}",
                    "customer_id": cust,
                    "facility": f"{cust}-FAC{f_idx}",
                    "amount_due": f"{tier:.2f}",
                    "due_date": (month + timedelta(days=30)).isoformat(),
                }
                inv_seq += 1
                invoices.append(inv)
                open_by_customer[cust].append(inv)

    def take(cust: str, k: int) -> list[dict]:
        pool = open_by_customer[cust]
        k = min(k, len(pool))
        picked = rng.sample(pool, k)
        for p in picked:
            pool.remove(p)
        return picked

    received = date(2026, 9, 1)
    plan = [name for name, count in SCENARIOS for _ in range(count)]
    rng.shuffle(plan)
    for scenario in plan:
        cust = rng.choice(customers)
        if len(open_by_customer[cust]) < 4:
            continue
        pid = f"PAY-{pay_seq}"
        pay_seq += 1
        received += timedelta(days=rng.randint(0, 1))
        day = received.isoformat()
        ref, status = "", "POSTED"

        if scenario == "remittance_list":
            invs = take(cust, rng.randint(1, 4))
            amount = sum(Decimal(i["amount_due"]) for i in invs)
            remittances.append({"payment_id": pid,
                                "invoice_ids": ";".join(i["invoice_id"] for i in invs),
                                "instruction": ""})
        elif scenario == "oldest_first":
            pool = sorted(open_by_customer[cust], key=lambda i: (i["due_date"], i["invoice_id"]))
            full = pool[: rng.randint(2, 4)]
            amount = sum(Decimal(i["amount_due"]) for i in full) + Decimal("500.00")
            remittances.append({"payment_id": pid, "invoice_ids": "",
                                "instruction": "OLDEST_FIRST"})
            # Mark the fully paid ones and the partially paid next one as used
            for i in pool[: len(full) + 1]:
                open_by_customer[cust].remove(i)
        elif scenario == "memo_reference":
            invs = take(cust, rng.randint(1, 2))
            amount = sum(Decimal(i["amount_due"]) for i in invs)
            ref = "Payment for " + " and ".join(i["invoice_id"].lower() if rng.random() < .3
                                                 else i["invoice_id"] for i in invs)
        elif scenario == "exact_amount":
            (inv,) = take(cust, 1)
            amount = Decimal(inv["amount_due"])
            ref = "ACH CREDIT"
        elif scenario == "combination":
            invs = take(cust, rng.randint(2, 3))
            amount = sum(Decimal(i["amount_due"]) for i in invs)
            ref = "EFT"
        elif scenario == "short_pay":
            invs = take(cust, 2)
            amount = sum(Decimal(i["amount_due"]) for i in invs) - Decimal("250.00")
            remittances.append({"payment_id": pid,
                                "invoice_ids": ";".join(i["invoice_id"] for i in invs),
                                "instruction": ""})
        elif scenario == "wrong_customer":
            other = rng.choice([c for c in customers if c != cust and open_by_customer[c]])
            (inv,) = take(other, 1)
            amount = Decimal(inv["amount_due"])
            remittances.append({"payment_id": pid, "invoice_ids": inv["invoice_id"],
                                "instruction": ""})
        elif scenario == "void":
            invs = take(cust, 1)
            amount = Decimal(invs[0]["amount_due"])
            status = "VOID"
            # Put the invoice back: a voided payment never really paid it
            open_by_customer[cust].extend(invs)
        else:  # no_info
            amount = Decimal(rng.randint(300, 9000)) + Decimal("0.37")
            ref = "DEPOSIT"

        payments.append({"payment_id": pid, "customer_id": cust, "amount": f"{amount:.2f}",
                         "received_date": day, "reference": ref, "status": status})
    return invoices, payments, remittances


def write(rows: list[dict], name: str, fields: list[str]) -> None:
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    inv, pay, rem = build()
    write(inv, "invoices.csv", ["invoice_id", "customer_id", "facility", "amount_due", "due_date"])
    write(pay, "payments.csv", ["payment_id", "customer_id", "amount", "received_date", "reference", "status"])
    write(rem, "remittances.csv", ["payment_id", "invoice_ids", "instruction"])
    print(f"Wrote {len(inv)} invoices, {len(pay)} payments, {len(rem)} remittances to {OUT}")
