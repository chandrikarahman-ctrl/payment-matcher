"""Run the matcher on a folder of CSVs.

    python run.py                      # uses ./data, writes ./output
    python run.py --data mydata --out results
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from matcher import GuardrailError, Matcher, verify
from matcher.io import load_invoices, load_payments, load_remittances, write_outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Match payments to open invoices, with guardrails.")
    parser.add_argument("--data", default="data", type=Path)
    parser.add_argument("--out", default="output", type=Path)
    args = parser.parse_args()

    invoices = load_invoices(args.data / "invoices.csv")
    payments = load_payments(args.data / "payments.csv")
    remittances = load_remittances(args.data / "remittances.csv")

    result = Matcher(invoices).run(payments, remittances)

    try:
        checks = verify(result, invoices, payments)
    except GuardrailError as e:
        # Fail loudly and write nothing. A wrong upload file is worse than none.
        print(f"STOPPED: {e}", file=sys.stderr)
        return 1

    print(write_outputs(result, payments, checks, args.out))
    print(f"Files written to {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
