# Evaluation Methodology

This document explains how Promotion Eval 2.0 measures a coding agent and why it is designed this way. It is more technical than the README but intentionally stops short of the held-out measurement details.

Three principles guide everything below:

> **Specify properties and outcomes, not implementation.**
>
> **Collect generously; score conservatively.**
>
> **Expose the requirement; hide the measurement instrument.**

---

## 1. From Capability to Result

The evaluation is built as a chain. Each link must be justified by the one above it.

```text
Capability            What ability are we trying to measure?
   ↓
Task specification    What the agent is asked to do (candidate-visible)
   ↓
Requirements          Specific, checkable business and interface rules (candidate-visible)
   ↓
Success properties    Named outcomes that show a requirement is met
   ↓
Graders               17 families, each covering a capability area
   ↓
Assertions            335 individual deterministic checks
   ↓
Results               PASS / FAIL / BLOCKED / ERROR per assertion, with evidence
```

**Capability.** Can a coding agent extend an unfamiliar, production-style codebase with a complex, interacting business feature while preserving that codebase's existing guarantees: correctness, concurrency safety, idempotency, payment consistency, and backward compatibility?

**Task specification.** [`candidate/TASK.md`](../candidate/TASK.md) describes the promotion system in business terms. [`candidate/PROMOTION_ADMINISTRATION_INTEROPERABILITY_CONTRACT.md`](../candidate/PROMOTION_ADMINISTRATION_INTEROPERABILITY_CONTRACT.md) defines the one programmatic interface the evaluator needs: a small HTTP/JSON admin API. The agent sees both.

**Requirements and success properties.** Each requirement is broken into success properties, which are observable statements of what "done" looks like. Example: *"a partial update changes only the requested fields; clearing a required field is rejected without changing anything."*

**Graders and assertions.** Grader families group related properties: baseline regression, administration, scope, economics by promotion type, stacking, MAP, codes and eligibility, checkout revalidation, redemption and idempotency, concurrency, tax and shipping, historical integrity, and customer-facing behavior. Each family runs controlled **scenarios**, and each scenario produces one or more **assertions**.

**Results.** Every assertion records its outcome, a concise expected and observed value, the linked requirements, and the evidence (for example, the HTTP exchanges involved).

---

## 2. Grade Observable Outcomes

The evaluator measures **what the application does**:

- the prices, discounts, tax, shipping, and totals a customer is shown and charged;
- what the simulated payment processor actually authorized and captured;
- whether redemption limits hold, including under concurrent checkouts;
- whether completed orders stay historically accurate after promotions or prices change;
- whether the admin API accepts valid changes and rejects invalid ones without partial updates;
- whether existing Northstar behavior still works.

It does **not** grade code style, file layout, class names, database schema, algorithm choice, or visual design. Source-code shape is not evidence of correctness.

The evidence hierarchy, in order of preference:

1. externally observable application behavior;
2. authoritative application state exposed through documented interfaces;
3. completed-order, payment, and redemption history;
4. customer-visible output.

---

## 3. Solution Independence

A fair evaluation must accept **every** correct solution, not just the one the evaluator's author would have written.

In practice:

- The agent may choose its own schema, models, services, numeric representation, locking strategy, discount-allocation approach, and UI structure. [`TASK.md`](../candidate/TASK.md) says so explicitly.
- The evaluator interacts only through Northstar's **established interfaces** (the storefront and admin pages existing consumers already use), the **published contract**, and **evaluator-owned systems** such as the payment processor.
- Where the task allows more than one correct outcome, for example a tie between equally priced reward items, every allowed outcome is accepted.
- Identifiers returned by the agent's API are treated as opaque. The evaluator does not assume a format.

Solution independence is also **tested**, not just intended. The evaluator's own test suite includes regression tests that change things a valid alternative implementation is free to change, and confirms the graders still behave correctly.

---

## 4. Deterministic Grading

Promotion arithmetic, payment amounts, redemption counts, concurrency outcomes, and API rejections are **objectively verifiable**. For behavior like that, a deterministic check is more reliable, cheaper, and more reproducible than a model-based judge.

All 335 scored assertions are deterministic.

The architecture includes a narrow, optional boundary for a model grader (LLM-as-judge). It is limited to one question: is a customer-facing message reasonably clear? It is held to strict rules: categorical PASS/FAIL, calibration against human-labeled examples, never deciding economics, and never overriding deterministic results. No model grader was configured or used in the reported trials.

---

## 5. Candidate-Visible Requirements vs. Held-Out Measurement

| The candidate sees | The candidate does not see |
|---|---|
| Every business requirement | Exact scenarios |
| The full admin API contract | Exact assertions and expected values |
| The full Northstar codebase and its tests | Fixture data and deliberately chosen boundary values |
| | Grader-validation implementations |

This separation matters in two directions:

- **Fairness.** Every assertion must be authorized by something the agent could read. A traceability audit must be able to answer: *"What candidate-visible requirement authorizes this check?"* If there is no defensible answer, the check is removed or the specification is corrected **before** trials.
- **Validity.** If exact tests were public, they would become optimization targets. A model could pass them without having the underlying capability.

---

## 6. Requirements Traceability

Every executable assertion carries:

```text
assertion_id
grader_id
scenario_id
success_property_ids[]
requirement source(s)
```

Each assertion result includes the text of the requirements and success properties it tests. When something fails, the report shows which promise was broken, not just which test.

---

## 7. Four Outcomes: PASS, FAIL, BLOCKED, ERROR

| Status | Meaning | Counts against the candidate? |
|---|---|---|
| **PASS** | The behavior was exercised and was correct. | — |
| **FAIL** | The behavior was exercised and was wrong. | Yes |
| **BLOCKED** | A prerequisite failed, so this behavior could not be validly exercised. | Recorded separately |
| **ERROR** | The evaluator or its infrastructure malfunctioned. | No |

BLOCKED prevents a single root failure from showing up as dozens of misleading downstream failures. For example, if a promotion never takes effect in the cart, the evaluator cannot test whether checkout revalidates it. Those checks are BLOCKED, not FAIL.

BLOCKED is never used to hide a failure the scenario actually reached. ERROR keeps evaluator bugs from ever being reported as candidate failures.

Failures also get a **failure category** (such as arithmetic, stacking, MAP, rounding, concurrency, idempotency, interoperability, or historical integrity), so analysis can group failures by root cause instead of counting them.

---

## 8. Collect Generously; Score Conservatively

The evaluator records far more than it scores: HTTP exchanges, payment-processor records, startup stages, and timing.

Scoring stays narrow and defensible:

- Correctness cannot be offset by efficiency.
- Many assertions failing from one root defect should not automatically create a disproportionate penalty.
- Raw assertion outcomes and failure categories are always reported alongside any aggregate.
- Weights and hard gates must be justified by the capability, not chosen to fit a convenient 100-point scale.

For these reasons, no single aggregate score is published. Results are reported as raw counts by grader family and failure category.

---

## 9. Grader Validation

A grader is software, and it can be wrong. Before candidate trials, the graders were validated in three ways (described conceptually here; the validation material itself is private).

**Known-good behavior.** A reference implementation of the Northstar surfaces the graders use, with promotion pricing written directly from the business specification and independently of the graders' expected-value tables. Every assertion must pass against it.

**Known-bad behavior.** Switchable defects, each replacing one rule with a *plausible* wrong implementation: the kind of mistake a real agent might make. Each defect must fail **exactly the assertions that target it**, and it must fail them for the intended reason, not because it broke something unrelated.

**Alternative-valid behavior.** Changes that a correct implementation is free to make, such as a different workspace layout, markup, line grouping, or persistence approach. These must not change grader outcomes.

The validation suite also tests the evaluator's own plumbing: deterministic fixture setup, the half-up rounding money oracle, concurrency orchestration, evidence capture, and correct attribution of FAIL vs. BLOCKED vs. ERROR. The evaluator itself is covered by an extensive regression and validation suite.

---

## 10. Post-Run Failure Analysis and Evaluator Correction

Candidate trials are also a test of the evaluator. When a result looks suspicious, the process is:

1. Reproduce the issue from the saved evidence.
2. Identify the requirement and success property involved.
3. Decide whether the candidate violated a visible requirement or the grader encoded an assumption the candidate could not have known.
4. Correct the grader or specification **only when justified**, never just to accept one candidate's preferred design.
5. Add a grader regression test, version the change, identify affected prior trials, and rerun where comparability requires it.

**Example from Trial 002.** The single failure involved how the candidate's admin API rejected a malformed promotion identifier. Before accepting it, I traced the assertion to the candidate-visible contract (opaque identifiers plus a required machine-readable error format). I confirmed that the grader accepts any reasonable error code and status, and that other valid implementations pass. Result: a legitimate candidate defect, and no evaluator change was needed. See [Trial 002 summary](../results/TRIAL_002_SUMMARY.md).

---

## 11. Reproducibility and Immutable Trials

- **Identical starting point.** Every trial begins from the same frozen Northstar snapshot, verified against recorded SHA-256 hashes.
- **Isolation.** Each candidate works in its own fresh workspace outside the evaluator repository, with no evaluator material in it or above it.
- **Sealing.** When the candidate finishes, the workspace is snapshotted, hashed, and frozen. Grading runs against the verified sealed snapshot, never against a live workspace.
- **Provenance.** Each trial records the evaluator commit, task and contract hashes, baseline version, candidate agent and model, and timestamps.
- **Immutable runs.** Each grading run writes to its own new directory, and earlier results are never overwritten.

See [`EVALUATION_ARCHITECTURE.md`](EVALUATION_ARCHITECTURE.md) for how these pieces fit together.
