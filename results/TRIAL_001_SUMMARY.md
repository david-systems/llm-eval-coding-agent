# Trial 001 — Codex / GPT-5.6 Luna

*Sanitized summary. Raw grader output, exact scenarios, and assertion-level evidence are held out.*

## Configuration

| | |
|---|---|
| Evaluation | Promotion Eval 2.0 |
| Candidate agent | Codex |
| Model (as recorded) | GPT-5.6 Luna |
| Starting point | Frozen Northstar v1.0.1 (hash-verified, 88 files) |
| Candidate-visible inputs | [`TASK.md`](../candidate/TASK.md), [`PROMOTION_ADMINISTRATION_INTEROPERABILITY_CONTRACT.md`](../candidate/PROMOTION_ADMINISTRATION_INTEROPERABILITY_CONTRACT.md) |
| Date | 2026-10-01 |
| Submission | Sealed workspace: 2 files added, 4 modified |
| Grading | 17 grader families, 113 scenarios, 335 assertions; about 11 minutes |

## Purpose

This was the first full end-to-end run of the evaluator against a real coding agent. Its main goal was to exercise the whole pipeline (trial creation, agent execution, sealing, grading, and reporting) on a real submission, not to measure frontier-model performance.

## Aggregate Result

| PASS | FAIL | BLOCKED | ERROR | Total |
|---|---|---|---|---|
| 168 | 104 | 63 | 0 | 335 |

At the scenario level: 21 passed, 71 failed, and 21 were blocked, out of 113.

## Outcomes by Grader Family

| Family | Capability area | PASS | FAIL | BLOCKED |
|---|---|---|---|---|
| G01 | Frozen baseline regression (existing behavior preserved) | 26 | 0 | 0 |
| G02 | Promotion administration & interoperability | 76 | 11 | 9 |
| G03 | Product scope & qualification | 2 | 6 | 0 |
| G04 | Product-level promotion economics | 0 | 7 | 0 |
| G05 | Order-level & threshold promotion economics | 4 | 8 | 0 |
| G06 | Buy X → Get Y reward promotions | 2 | 7 | 0 |
| G07 | Buy X → order benefit | 2 | 6 | 0 |
| G08 | Free product & free shipping | 5 | 7 | 0 |
| G09 | Common basis & stacking | 2 | 10 | 0 |
| G10 | MAP (minimum advertised price) reconciliation | 0 | 6 | 0 |
| G11 | Codes, activation & eligibility | 23 | 12 | 8 |
| G12 | Checkout revalidation | 0 | 0 | 31 |
| G13 | Redemption & idempotency | 5 | 8 | 5 |
| G14 | Redemption concurrency | 0 | 0 | 8 |
| G15 | Tax, shipping & monetary integrity | 0 | 10 | 0 |
| G16 | Historical integrity | 15 | 5 | 0 |
| G17 | Customer-facing behavior | 6 | 1 | 2 |
| **Total** | | **168** | **104** | **63** |

## Important Findings

**The existing application was preserved.** All 26 baseline-regression assertions passed. The agent did not break Northstar's catalog, carts, checkout, payments, or admin behavior.

**The promotion system was substantially incomplete.** The submission added a small promotion service (under 100 lines) and a migration. Most promotion types, stacking rules, MAP handling, and monetary rules were missing or incorrect.

**The 104 failures by category:**

| Failure category | Count |
|---|---|
| Promotion arithmetic | 24 |
| Code activation | 12 |
| Interoperability (admin API contract) | 11 |
| Stacking / common basis | 11 |
| Shipping | 9 |
| Redemption accounting | 8 |
| MAP constraint | 7 |
| Scope / qualification | 6 |
| Historical integrity | 5 |
| Zero-price floor | 4 |
| Rounding | 3 |
| Tax | 3 |
| Customer communication | 1 |

**BLOCKED worked as designed.** Many advanced checks, such as checkout revalidation and concurrent redemption, depend on a promotion first taking effect in the cart. When that prerequisite failed, the evaluator reported those checks as **BLOCKED** rather than FAIL. This keeps one root failure from inflating the failure count, and it shows plainly that those capabilities were never actually exercised.

**No evaluator errors.** Zero ERROR results means every grader ran to completion against this submission, and no infrastructure problem was counted against the candidate.

## What This Trial Validated About the Evaluator

- The pipeline worked end to end on a real, imperfect submission.
- Graders produced meaningful, distinguishable PASS / FAIL / BLOCKED results instead of failing all at once.
- Baseline regression is measured independently of new-feature progress: a candidate can preserve existing behavior and still fail the new task, and the results show both.

## Limitations

- A single trial. It describes this run, not the model's typical performance.
- The run was primarily an evaluator-validation exercise.
- This trial was graded with an earlier one-off grading script, before the permanent grading command existed. The grader families, task, contract, and frozen baseline were identical to Trial 002, so the assertion counts are directly comparable.
- Agent trajectory, token usage, and cost were not captured as part of this trial's results.
