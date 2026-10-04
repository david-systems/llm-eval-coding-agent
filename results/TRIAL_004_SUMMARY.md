# Trial 004 — Claude Code / Claude Haiku 4.5 High

*Sanitized summary. Raw grader output, exact scenarios, and assertion-level evidence are held out.*

## Configuration

| | |
|---|---|
| Evaluation | Promotion Eval 2.0 |
| Candidate agent | Claude Code |
| Model (as recorded) | Claude Haiku 4.5 (effort: High) |
| Starting point | Frozen Northstar v1.0.1 (hash-verified, 88 files) |
| Candidate-visible inputs | [`TASK.md`](../candidate/TASK.md), [`PROMOTION_ADMINISTRATION_INTEROPERABILITY_CONTRACT.md`](../candidate/PROMOTION_ADMINISTRATION_INTEROPERABILITY_CONTRACT.md) |
| Date | 2026-10-04 |
| Submission | Sealed workspace: 3 files added, 3 modified |
| Grading | 17 grader families, 113 scenarios, 335 assertions; 646.5 seconds |

## Purpose

This was an independent candidate trial using a smaller model with the same agent as Trial 003. It was graded with the same task, contract, frozen baseline, grader families, and evaluator version as Trial 003, so the assertion counts are directly comparable.

## Aggregate Result

| PASS | FAIL | BLOCKED | ERROR | Total |
|---|---|---|---|---|
| 58 | 64 | 213 | 0 | 335 |

At the scenario level: 11 passed, 22 failed, and 80 were blocked, out of 113.

## Outcomes by Grader Family

| Family | Capability area | PASS | FAIL | BLOCKED |
|---|---|---|---|---|
| G01 | Frozen baseline regression (existing behavior preserved) | 26 | 0 | 0 |
| G02 | Promotion administration & interoperability | 13 | 46 | 37 |
| G03 | Product scope & qualification | 0 | 0 | 8 |
| G04 | Product-level promotion economics | 0 | 0 | 7 |
| G05 | Order-level & threshold promotion economics | 3 | 0 | 9 |
| G06 | Buy X → Get Y reward promotions | 0 | 0 | 9 |
| G07 | Buy X → order benefit | 0 | 0 | 8 |
| G08 | Free product & free shipping | 5 | 1 | 6 |
| G09 | Common basis & stacking | 0 | 0 | 12 |
| G10 | MAP (minimum advertised price) reconciliation | 0 | 1 | 5 |
| G11 | Codes, activation & eligibility | 10 | 11 | 22 |
| G12 | Checkout revalidation | 0 | 0 | 31 |
| G13 | Redemption & idempotency | 0 | 0 | 18 |
| G14 | Redemption concurrency | 0 | 0 | 8 |
| G15 | Tax, shipping & monetary integrity | 1 | 0 | 9 |
| G16 | Historical integrity | 0 | 0 | 20 |
| G17 | Customer-facing behavior | 0 | 5 | 4 |
| **Total** | | **58** | **64** | **213** |

## Important Findings

**The existing application was preserved.** All 26 baseline-regression assertions passed. The agent did not break Northstar's catalog, carts, checkout, payments, or admin behavior.

**The promotion system was substantially incomplete.** The submission added a promotion service, an admin API module, and a migration, and changed three existing files. No storefront templates were changed, so the cart's promotion-code entry and the customer-facing promotion display required by the task were not present.

**Most failures trace to two interface gaps.**

| Failure area | FAIL count |
|---|---|
| Admin API interoperability (G02) | 46 |
| Code entry, activation & eligibility (G11) | 11 |
| Customer-facing behavior (G17) | 5 |
| Free product (G08) | 1 |
| MAP constraint (G10) | 1 |

The evaluator establishes promotions through the documented admin API. In this submission, most promotion-creation requests were rejected, and the rejections did not carry the machine-readable error body the contract requires. Separately, the cart did not provide the documented promotion-code entry interface.

**BLOCKED dominated this result, and it worked as designed.** Because promotions could not be created through the contract, and codes could not be entered at the cart, most downstream checks (economics, stacking, MAP, checkout revalidation, redemption, concurrency, and historical integrity) had no promotion to exercise. The evaluator reported those 213 assertions as **BLOCKED**, not FAIL. They are not 213 independent candidate defects: they are capabilities the evaluator could not reach, so this run shows neither success nor failure for them.

**The blocking prerequisites are satisfiable.** Trial 003 was graded with the same evaluator version and had zero FAIL and zero BLOCKED results, so a contract-conforming implementation can create every promotion the evaluator needs.

**No evaluator errors.** Zero ERROR results means every grader ran to completion against this submission, and no infrastructure problem was counted against the candidate.

## Interpretation

Trials 003 and 004 used the same agent, task, and evaluator version and produced very different results: 335 PASS versus 58 PASS. The evaluation clearly separated these two candidates. Trial 004 resembles Trial 001: the baseline was preserved, but the new feature was largely missing, and much of the evaluation was blocked behind unmet prerequisites.

## Limitations

- A single trial. It describes this run, not the model's typical performance.
- The large BLOCKED count means many capabilities were never exercised. This run gives no evidence, positive or negative, about them.
- Scoring measures the final application only. Agent trajectory, token usage, and cost were not captured as part of this trial's results.
