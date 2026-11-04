# Payment matching summary

- Payments processed: 82 (plus 6 voided, skipped)
- Cash received: $359,721.85
- Applied: $217,100.00 (60%)
- Sent to review: $142,621.85 (40%)

## Applied, by confidence

| Confidence | Amount | Needs approval |
|---|---|---|
| HIGH | $167,600.00 | No |
| MEDIUM | $49,500.00 | Yes |
| LOW | $0.00 | Yes |

## Review queue, by reason

| Reason | Payments | Amount |
|---|---|---|
| Ambiguous match | 21 | $70,000.00 |
| Short payment | 5 | $23,950.00 |
| Too many candidates | 4 | $21,570.74 |
| Invalid invoice reference | 4 | $8,575.00 |
| No information | 3 | $18,526.11 |

## Guardrail checks

- PASS: Every dollar of every payment is either applied or in the review queue
- PASS: No invoice is over-applied
- PASS: No payment is applied to another customer's invoice
- PASS: No voided payment is applied
- PASS: Every application row is a positive amount
