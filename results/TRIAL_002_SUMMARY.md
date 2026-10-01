# Trial 002 — Codex / GPT-5.6 Sol High

*Sanitized summary. Raw grader output, exact scenarios, and assertion-level evidence are held out.*

## Configuration

| | |
|---|---|
| Evaluation | Promotion Eval 2.0 |
| Candidate agent | Codex |
| Model (as recorded) | GPT-5.6 Sol High |
| Starting point | Frozen Northstar v1.0.1 (hash-verified, 88 files) |
| Candidate-visible inputs | [`TASK.md`](../candidate/TASK.md), [`PROMOTION_ADMINISTRATION_INTEROPERABILITY_CONTRACT.md`](../candidate/PROMOTION_ADMINISTRATION_INTEROPERABILITY_CONTRACT.md) |
| Date | 2026-10-01 |
| Submission | Sealed workspace: 5 files added, 13 modified (including the agent's own promotion tests) |
| Grading | 17 grader families, 113 scenarios, 335 assertions; 702.8 seconds |

## Purpose

This was the second independent validation run, using a stronger model. The goal was to exercise the deeper parts of the evaluator (stacking, MAP, checkout revalidation, concurrency, idempotency, and historical integrity), which Trial 001 never reached.

## Aggregate Result

| PASS | FAIL | BLOCKED | ERROR | Total |
|---|---|---|---|---|
| **334** | 1 | 0 | 0 | 335 |

At the scenario level, 112 of 113 passed.

## Outcomes by Grader Family

| Family | Capability area | PASS | FAIL |
|---|---|---|---|
| G01 | Frozen baseline regression (existing behavior preserved) | 26 | 0 |
| G02 | Promotion administration & interoperability | 95 | **1** |
| G03 | Product scope & qualification | 8 | 0 |
| G04 | Product-level promotion economics | 7 | 0 |
| G05 | Order-level & threshold promotion economics | 12 | 0 |
| G06 | Buy X → Get Y reward promotions | 9 | 0 |
| G07 | Buy X → order benefit | 8 | 0 |
| G08 | Free product & free shipping | 12 | 0 |
| G09 | Common basis & stacking | 12 | 0 |
| G10 | MAP (minimum advertised price) reconciliation | 6 | 0 |
| G11 | Codes, activation & eligibility | 43 | 0 |
| G12 | Checkout revalidation | 31 | 0 |
| G13 | Redemption & idempotency | 18 | 0 |
| G14 | Redemption concurrency | 8 | 0 |
| G15 | Tax, shipping & monetary integrity | 10 | 0 |
| G16 | Historical integrity | 20 | 0 |
| G17 | Customer-facing behavior | 9 | 0 |
| **Total** | | **334** | **1** |

## Important Findings

**Every substantive business-logic grader passed.** That covers promotion economics for all 11 types, scope targeting, stacking on a common basis, MAP enforcement, codes and eligibility, checkout revalidation, redemption accounting, idempotent retries, concurrent redemption of limited promotions, payment consistency, tax and shipping, and historical order integrity.

**Existing behavior was preserved.** All 26 baseline-regression assertions passed.

**The single failure was an interoperability issue, not a business-logic error.** The admin API contract requires every rejected request to return a JSON body with a machine-readable `error` field. It also says promotion identifiers are opaque, so their format is not prescribed. The candidate's API returned the correct error format for unknown promotions, but it declared the identifier as an integer in its web framework. When the evaluator sent an identifier that did not match that format, the framework rejected the request before the candidate's code ran. The response was the framework's default validation-error format, which lacks the required `error` field.

**The failure was audited before it was accepted.** Before counting it, I checked that:

1. the requirement is stated in the candidate-visible contract (opaque identifiers plus the error-response rule);
2. the grader tests the requirement, not a preferred implementation: any non-success status and any non-empty error code passes;
3. other valid implementations, such as string identifiers or a custom validation-error handler, pass the same check.

Conclusion: **a genuine, minor candidate defect.** It is not a grader bug, and no evaluator change was needed.

## Interpretation

This result indicates that **this particular task is approaching saturation for a strong coding agent.** One run nearly cleared a 335-assertion held-out evaluation, including the concurrency and payment-consistency checks.

That is not a claim that all frontier models would do this well, or that this model would do it on every run. The useful conclusion is about **what to measure next**. Adding increasingly obscure promotion edge cases would mostly test trivia. The next evaluation instead targets a different capability: long-horizon, multi-source, organizational reasoning.

## Limitations

- A single trial. This shows what one run achieved, not a pass rate.
- Near-ceiling performance limits how well this task can separate strong models.
- Scoring measures the final application only. Agent trajectory, token usage, and cost were not captured as part of this trial's results.
