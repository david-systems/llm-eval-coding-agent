# Trial 003 — Claude Code / Claude Sonnet 5.5 High

*Sanitized summary. Raw grader output, exact scenarios, and assertion-level evidence are held out.*

## Configuration

| | |
|---|---|
| Evaluation | Promotion Eval 2.0 |
| Candidate agent | Claude Code |
| Model (as recorded) | Claude Sonnet 5.5 (effort: High) |
| Starting point | Frozen Northstar v1.0.1 (hash-verified, 88 files) |
| Candidate-visible inputs | [`TASK.md`](../candidate/TASK.md), [`PROMOTION_ADMINISTRATION_INTEROPERABILITY_CONTRACT.md`](../candidate/PROMOTION_ADMINISTRATION_INTEROPERABILITY_CONTRACT.md) |
| Date | 2026-10-04 |
| Submission | Sealed workspace: 20 files added, 17 modified (including the agent's own promotion tests) |
| Grading | 17 grader families, 113 scenarios, 335 assertions; 691.5 seconds |

## Purpose

This was the first independent candidate trial using a different agent and model family from Trials 001 and 002. It was graded with the same task, contract, frozen baseline, and grader families, so the assertion counts are directly comparable.

## Aggregate Result

| PASS | FAIL | BLOCKED | ERROR | Total |
|---|---|---|---|---|
| **335** | 0 | 0 | 0 | 335 |

At the scenario level, all 113 passed.

## Outcomes by Grader Family

| Family | Capability area | PASS | FAIL |
|---|---|---|---|
| G01 | Frozen baseline regression (existing behavior preserved) | 26 | 0 |
| G02 | Promotion administration & interoperability | 96 | 0 |
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
| **Total** | | **335** | **0** |

## Important Findings

**Every grader family passed completely.** That covers the admin API contract, promotion economics for all 11 types, scope targeting, stacking on a common basis, MAP enforcement, codes and eligibility, checkout revalidation, redemption accounting, idempotent retries, concurrent redemption of limited promotions, tax and shipping, historical order integrity, and customer-facing display.

**Existing behavior was preserved.** All 26 baseline-regression assertions passed.

**The admin API contract was fully satisfied.** This includes the error-response requirement for malformed promotion identifiers, the one assertion missed in Trial 002.

**No evaluator errors.** Zero ERROR results means every grader ran to completion against this submission.

## Interpretation

Together with Trial 002, this result indicates that **this task is saturated for the strongest candidates tested.** Two independent runs, from different agents and model families, cleared or nearly cleared the full 335-assertion held-out evaluation.

That is not a claim that this model would score 335/335 on every run, or that it outperforms Trial 002's model in general. A one-assertion difference between single runs is not evidence of a meaningful capability gap. At this ceiling, the task no longer separates strong candidates from each other.

## Limitations

- A single trial. This shows what one run achieved, not a pass rate.
- At the ceiling, the evaluation cannot show how much further this candidate's capability extends.
- Scoring measures the final application only. Agent trajectory, token usage, and cost were not captured as part of this trial's results.
