# Payment Matcher

**Match incoming customer payments to open invoices, and refuse to guess when the answer isn't clear.**

This is a public, synthetic-data version of a cash application tool I built at work. Every customer, invoice and payment in this repo is fictional. The logic and guardrails mirror the real thing.

## The problem

In B2B billing, customers often pay without saying which invoices the money is for. A single payment can cover dozens of invoices across many facilities. When the remittance details are missing, cash sits "unapplied": the customer looks overdue, collections chases money that was already paid, and finance can't close cleanly.

The obvious fix is to match on amount. The problem is that subscription businesses bill standard prices, so one customer can have eight open invoices for exactly $4,200.00. An amount-only matcher will confidently apply cash to the wrong one, and nobody notices until a customer disputes it.

## What this does

Each payment goes down a ladder of strategies, from most to least trustworthy. The first one that gives a **single, unambiguous** answer wins. If a strategy finds more than one plausible answer, the payment stops and goes to a person.

| Step | Strategy | Confidence | Human approval |
|---|---|---|---|
| 1 | Remittance lists the invoices | HIGH | No |
| 2 | Remittance says "apply oldest first" | HIGH | No |
| 3 | Invoice number found in the payment memo | MEDIUM | Yes |
| 4 | Exactly one open invoice matches the amount | MEDIUM | Yes |
| 5 | Exactly one combination of invoices adds up to the amount | LOW | Yes |
| 6 | Anything else | Review queue | Yes |

Outputs:

- `output/application_template.csv`: rows ready for upload, each with a confidence level and an approval flag
- `output/review_queue.csv`: cash the tool would not apply, with a plain-English reason
- `output/summary.md`: totals, a breakdown by confidence and review reason, and guardrail results

## Guardrails

These come from real mistakes, mine and the system's.

1. **Every dollar is accounted for.** Applied plus sent-to-review must equal cash received for every payment, or nothing is written.
2. **No invoice is ever over-applied.**
3. **Cash only goes to the customer who sent it.** A remittance pointing at another customer's invoice is rejected, not "fixed".
4. **Voided payments are excluded.** An early version of the real report double-counted voided payments. Now it's a check.
5. **One bad reference rejects the whole instruction.** If a remittance lists five invoices and one is wrong, the tool doesn't apply the other four and hope.
6. **Short payments are never split by guesswork.** Someone has to decide which invoice is short.
7. **The tool adds up rows itself** instead of trusting system-calculated totals, because one billing system returned wrong sums.
8. **Fail loudly.** If any check fails, the run stops and writes no upload file. A wrong upload is worse than none.

## Results on the sample data

```
- Payments processed: 82 (plus 6 voided, skipped)
- Cash received: $359,721.85
- Applied: $217,100.00 (60%)
- Sent to review: $142,621.85 (40%)

| Reason                    | Payments | Amount     |
|---------------------------|----------|------------|
| Ambiguous match           | 21       | $70,000.00 |
| Short payment             | 5        | $23,950.00 |
| Too many candidates       | 4        | $21,570.74 |
| Invalid invoice reference | 4        | $8,575.00  |
| No information            | 3        | $18,526.11 |

PASS: Every dollar of every payment is either applied or in the review queue
PASS: No invoice is over-applied
PASS: No payment is applied to another customer's invoice
PASS: No voided payment is applied
PASS: Every application row is a positive amount
```

**How to read this:** 40% going to review is the point, not a failure. The largest review bucket is "Ambiguous match": payments where several invoices share the exact amount. A less careful tool would have applied all $70,000 of it, and some of it would be wrong. The tool's value is the 60% it handles safely, plus a review queue that tells a person exactly why each item needs them.

The biggest lever for reducing the review queue isn't a smarter algorithm. It's getting remittance details captured in the first place. That's a process fix, and it's what I'd prioritize next in a real rollout.

## Run it

Requires Python 3.10+. No external packages.

```bash
python data/generate_sample_data.py   # regenerate the synthetic dataset (optional)
python run.py                         # match and write results to ./output
python -m unittest discover tests     # 13 tests
```

## Project layout

```
payment-matcher/
  run.py                      command-line entry point
  matcher/
    models.py                 invoices, payments, remittances, results
    match.py                  the strategy ladder
    guardrails.py             post-run checks; any failure stops the run
    io.py                     CSV in, CSV and summary out
  data/
    generate_sample_data.py   synthetic data with realistic messy scenarios
    invoices.csv, payments.csv, remittances.csv
  output/                     results from the sample run
  tests/test_matcher.py
```

## Design decisions

- **Ambiguity stops the ladder.** If an exact-amount search finds several matches, the tool doesn't fall through to a weaker strategy hoping for a different answer.
- **Payments are processed oldest first**, so an earlier payment claims an invoice before a later duplicate does. The duplicate goes to review as "already paid".
- **Combination search is capped** (up to 4 invoices, at most 15 candidates). Beyond that, too many combinations add up by coincidence, so the tool says so instead of picking one.
- **Money is `Decimal`, never float.**

## What I'd add next

- Fuzzy matching of customer names on payments that arrive without a customer ID
- A precision report: of the MEDIUM and LOW matches reviewers approved, how many were right? That would tell us which strategies can move up a confidence level.
- An AI step that reads remittance emails and PDFs into `remittances.csv`, with every extracted value checked against the source document

---

Built by [Musharrat Rahman](https://linkedin.com/in/musharrat-rahman). MIT licensed.
