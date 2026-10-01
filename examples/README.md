# Illustrative Examples (Not Held-Out Material)

> **Everything in this folder is invented for explanation.** None of it is a real evaluator scenario, assertion, fixture, or trial result. Product names, prices, IDs, and observed values are fictional, and the schema is simplified.

## What This Shows

[`illustrative_assertion_results.json`](illustrative_assertion_results.json) shows the *shape* of the evaluator's reasoning for a single, simple requirement:

1. **Traceability.** The scenario quotes the exact candidate-visible requirements (from [`candidate/TASK.md`](../candidate/TASK.md)) that authorize its checks.
2. **Observable outcomes.** Each assertion compares an expected and an observed business outcome, such as merchandise subtotal, tax, or amount captured, not code structure.
3. **Four outcomes:**

| Status | In the example | Why it matters |
|---|---|---|
| PASS | The discounted subtotal is correct. | — |
| FAIL | Tax was computed on the pre-discount price. | A real candidate defect, with a failure category for root-cause analysis |
| BLOCKED | The promotion could not be created, so a downstream checkout check never ran. | Keeps one root failure from inflating the failure count |
| ERROR | The evaluator's own infrastructure failed. | Evaluator problems are never blamed on the candidate |

## How the Example Values Work

```text
Product price                      $80.00
25% Percentage Off Product        -$20.00
Merchandise after promotions       $60.00
Tax at 8.25% on $60.00              $4.95   ← expected
Tax at 8.25% on $80.00              $6.60   ← the illustrated mistake
```

## Why There Are No Real Examples Here

The real scenarios, values, and assertions are **held out**. Publishing them, or close variants, would turn them into an answer key that future candidate agents could optimize against. A future model could then pass without having the underlying capability.

This example deliberately uses an easy, non-boundary case that follows directly from the public task text. It reveals nothing beyond what [`TASK.md`](../candidate/TASK.md) already says.
