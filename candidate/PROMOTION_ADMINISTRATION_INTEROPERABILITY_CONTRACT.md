# Promotion Eval 2.0 — Promotion Administration Interoperability Contract

**Status:** Contract 1.0 — candidate-visible specification  
**Scope:** Programmatic promotion administration  
**Applies to:** Promotion Eval 2.0 candidate environment derived from Northstar v1.0.1

---

## 1. Purpose and Governing Principle

Promotion Eval 2.0 requires the candidate to add a complex, programmatically administrable promotion system to Northstar.

Canonical Northstar v1.0.1 intentionally contains no promotion subsystem or promotion-administration API. Because candidates are free to design their own database schema, models, services, modules, algorithms, and persistence strategy, the evaluator cannot depend on discovering candidate-specific internals.

This contract therefore defines a stable HTTP/JSON administration boundary through which an authenticated Northstar administrator can create, read, update, archive/restore, and delete promotions.

The contract standardizes **administrator intent and observable interoperability, not solution design**.

Every semantic field or operation in this contract must trace to a candidate-visible Promotion Eval 2.0 business requirement. The contract must not expose evaluator-only calculations or require a particular implementation merely because doing so would make grading easier.

> **We standardize the observable boundary, not the solution behind it.**

---

## 2. Solution Independence

A conforming candidate remains free to choose:

- database tables, columns, relationships, constraints, and indexes;
- ORM or no ORM;
- classes, functions, modules, and services;
- persistence technology;
- internal monetary and percentage representation;
- internal scope representation;
- promotion evaluation algorithms;
- promotion processing order, provided required economics are order-independent;
- stacking implementation;
- MAP reconciliation implementation;
- discount-allocation implementation;
- locking, transaction, and concurrency strategy;
- redemption persistence strategy;
- historical snapshot implementation;
- administration UI structure and design.

The wire fields defined here do not imply corresponding internal fields, database columns, classes, or variables.

---

## 3. Transport and Required Operations

The administration boundary uses HTTP with JSON.

Required route prefix:

```text
/admin/api/promotions
```

Required operations:

| Operation | Method | Route |
|---|---|---|
| Create promotion | `POST` | `/admin/api/promotions` |
| Read promotion | `GET` | `/admin/api/promotions/{id}` |
| Update promotion | `PATCH` | `/admin/api/promotions/{id}` |
| Delete promotion | `DELETE` | `/admin/api/promotions/{id}` |
| Read completed-order reconciliation | `GET` | `/admin/api/orders/{order_id}/reconciliation` |

No list/search endpoint is required. The reconciliation read is defined in §15A.

Lifecycle changes use `PATCH`; separate activate, deactivate, archive, or restore routes are not required.

`{id}` is an opaque candidate-chosen promotion identifier returned by the create operation. Its format is not prescribed. The evaluator must not infer database or storage semantics from it.

The candidate may expose additional routes or response fields, but the evaluator does not depend on undocumented extensions.

---

## 4. Authentication and Authorization

The API must use Northstar's existing administrator authentication.

The candidate must not introduce an evaluator-only credential, privileged backdoor, or administration bypass.

Unauthenticated callers must not be able to perform privileged promotion administration.

State-changing operations are protected by Northstar's existing CSRF protection: a state-changing request without a valid token must be rejected without mutation. The evaluator presents the session's token in Northstar's existing `X-CSRF-Token` request header.

Rejections produced by Northstar's existing authentication and CSRF protection may keep Northstar's existing response formats; they must be non-2xx and must not mutate promotion state. The error contract in §17 applies to rejections produced by the promotion administration operations themselves.

The evaluator may use the ordinary Northstar administrator login/session/CSRF flow and then call this API.

This contract specifies observable authorization behavior, not the candidate's internal authorization architecture.

---

## 5. Normative Wire Vocabulary

The following representations are Contract 1.0 requirements.

### 5.1 Common fields

| Field | JSON representation | Meaning |
|---|---|---|
| `name` | non-empty string | Administrative promotion name |
| `type` | closed enum string | Promotion mechanism; §6 |
| `active` | boolean | Independent active/inactive state |
| `archived` | boolean | Independent archival state |
| `activation` | `"automatic"` or `"code"` | Activation method |
| `code` | string or `null` | Customer-entered code where applicable |
| `starts_at` | RFC 3339 string or `null` | Optional validity start |
| `ends_at` | RFC 3339 string or `null` | Optional validity end |
| `eligibility` | eligibility object | Customer eligibility; §8 |
| `global_redemption_limit` | positive integer or `null` | Optional global successful-redemption cap |
| `per_customer_redemption_limit` | positive integer or `null` | Optional per-customer successful-redemption cap |
| `stackable` | boolean | Code-promotion stacking setting where applicable |
| `map_override` | boolean | Whether this promotion may override MAP |
| `trigger_scope` | scope object or `null` | Qualification scope where applicable |
| `reward_scope` | scope object or `null` | Product benefit/reward scope where applicable |
| `percentage` | decimal string or `null` | Type-specific percentage |
| `amount` | decimal-dollar string or `null` | Type-specific fixed monetary amount |
| `threshold` | decimal-dollar string or `null` | Type-specific merchandise threshold |
| `trigger_quantity` | positive integer or `null` | X quantity where applicable |
| `reward_quantity` | positive integer or `null` | Y quantity for Buy-X/Get-Y |
| `reward_limit` | positive integer or `null` | Z maximum rewarded units/order |

### 5.2 Booleans

Boolean fields use actual JSON booleans only:

```json
true
```

```json
false
```

The following are not valid Boolean representations:

```text
0
1
"true"
"false"
"yes"
"no"
"enabled"
"disabled"
```

### 5.3 Money

`amount` and `threshold` use decimal-dollar strings with exactly two fractional digits.

Valid:

```json
{"amount":"25.00","threshold":"100.00"}
```

Invalid examples:

```json
{"amount":25}
```

```json
{"amount":"25"}
```

```json
{"amount":"$25.00"}
```

This representation does not prescribe internal storage. Integer cents, exact decimal types, database numeric types, or another exact representation are all permitted internally.

### 5.4 Percentages

`percentage` is a decimal string representing percentage points.

```json
{"percentage":"10"}
```

means 10%.

```json
{"percentage":"12.5"}
```

means 12.5%.

```json
{"percentage":"100"}
```

means 100%.

The wire contract does not use fractional-rate notation such as `"0.10"` to mean 10%.

### 5.5 Counts and limits

Quantities and configured redemption limits are positive JSON integers.

Zero and negative quantities or limits are invalid.

### 5.6 Date/time

`starts_at` and `ends_at` use RFC 3339 timestamps with an explicit UTC offset or `Z`.

Valid examples:

```json
{"starts_at":"2026-10-01T00:00:00Z"}
```

```json
{"ends_at":"2026-10-31T23:59:59-07:00"}
```

Naive timestamps without an offset are invalid.

Internal datetime storage remains unrestricted.

---

## 6. Promotion Type Enum

`type` must be exactly one of:

```text
percentage_off_product
fixed_amount_off_product
percentage_off_order
fixed_amount_off_order
spend_threshold_fixed_off_order
spend_threshold_percentage_off_order
buy_x_get_y_percentage_off
buy_x_fixed_off_order
buy_x_percentage_off_order
free_product
free_shipping
```

These values are closed Contract 1.0 enum values. Aliases are not part of the contract.

They identify business mechanisms only; they do not prescribe classes, tables, strategies, inheritance, or internal enum values.

---

## 7. Product Scope Contract

Trigger Scope and Reward Scope use the same two-mode representation.

### 7.1 Explicit SKU mode

```json
{
  "mode":"sku",
  "skus":["TH-0900","042"]
}
```

Rules:

- `mode` must equal `"sku"`;
- `skus` contains at least one value;
- every SKU is a JSON string;
- exact SKU strings must be preserved and are never numerically coerced;
- attribute fields must not be mixed into SKU mode.

For example:

```text
"042"
"42"
"0042"
```

are distinct SKU strings.

### 7.2 Attribute-filter mode

An attribute-filter scope is a JSON object with `mode` equal to `"attributes"` and any of the optional fields
`brands`, `categories`, and `subcategories`. Each present field is an array of strings naming Northstar brands,
categories, or subcategories respectively.

Rules:

- `mode` must equal `"attributes"`;
- at least one of `brands`, `categories`, or `subcategories` is populated;
- omitted dimensions impose no restriction;
- multiple values within a dimension use the task-defined OR semantics;
- populated dimensions combine using the task-defined AND semantics;
- `skus` must not be mixed into attribute mode.

The contract does not prescribe how scopes are stored, queried, indexed, or represented internally.

---

## 8. Customer Eligibility Contract

`eligibility.mode` is exactly one of:

```text
everyone
customer_levels
customers
```

### 8.1 Everyone

```json
{
  "mode":"everyone"
}
```

`levels` and `customer_ids` must not be supplied.

### 8.2 Customer levels

```json
{
  "mode":"customer_levels",
  "levels":["retail","contractor"]
}
```

`levels` contains at least one value.

Allowed customer-level values are exactly Northstar's customer-level values:

```text
retail
contractor
vip
```

`customer_ids` must not be supplied.

### 8.3 Specific registered customers

```json
{
  "mode":"customers",
  "customer_ids":[12,31]
}
```

`customer_ids` contains at least one existing registered Northstar customer identifier.

Specific-customer eligibility reuses Northstar's existing stable customer identity rather than creating a second identity system.

`levels` must not be supplied.

---

## 9. Activation and Codes

`activation` is exactly:

```text
automatic
```

or:

```text
code
```

### 9.1 Automatic

For:

```json
{"activation":"automatic"}
```

no customer-entered code is required.

`code` must be omitted or `null`.

### 9.2 Code-triggered

For:

```json
{"activation":"code"}
```

a non-empty `code` is required.

Code normalization, uniqueness, reservation, application, and customer feedback follow the Promotion Eval 2.0 business requirements.

The API does not expose `normalized_code` as an administrator-settable field. Normalization is required behavior, not administrator-provided state.

### 9.3 Free Product

`free_product` is code-triggered only.

Therefore:

```json
{
  "type":"free_product",
  "activation":"automatic"
}
```

is invalid.

---

## 10. Type-Specific Minimum Configuration

The following table defines the minimum economic configuration for each promotion mechanism.

| Type | Required type-specific fields | Optional qualification fields |
|---|---|---|
| `percentage_off_product` | `percentage`, `reward_scope` | — |
| `fixed_amount_off_product` | `amount`, `reward_scope` | — |
| `percentage_off_order` | `percentage` | `trigger_scope` |
| `fixed_amount_off_order` | `amount` | `trigger_scope` |
| `spend_threshold_fixed_off_order` | `threshold`, `amount` | `trigger_scope` |
| `spend_threshold_percentage_off_order` | `threshold`, `percentage` | `trigger_scope` |
| `buy_x_get_y_percentage_off` | `trigger_scope`, `trigger_quantity`, `reward_scope`, `reward_quantity`, `percentage`, `reward_limit` | — |
| `buy_x_fixed_off_order` | `trigger_scope`, `trigger_quantity`, `amount` | — |
| `buy_x_percentage_off_order` | `trigger_scope`, `trigger_quantity`, `percentage` | — |
| `free_product` | `reward_scope`, `activation:"code"`, `code` | — |
| `free_shipping` | — | `trigger_scope`, `threshold` |

Cross-cutting fields apply where permitted by the Promotion Eval 2.0 business specification.

### 10.1 Free Product

Free Product:

- is code-triggered only;
- requires a Reward Scope;
- makes exactly one eligible Reward Scope unit already present in the cart free;
- does not automatically add merchandise;
- does not increase cart quantity.

When more eligible Reward Scope units are present than may receive the reward, the lowest-priced eligible unit receives it. Equal-price boundary ties may be resolved to any economically equivalent tied unit.

### 10.2 Free Shipping

Free Shipping may exist without `trigger_scope` or `threshold`.

If configured, those fields provide the qualification behavior defined by the Promotion Eval 2.0 business specification.

---

## 11. Lifecycle, Date Validity, Redemption Capacity, and Code Reservation

These are separate concepts.

### 11.1 Administrative lifecycle

`active` and `archived` are independent administrative state fields.

An active, non-archived promotion may affect new transactions when all other requirements are satisfied.

An inactive promotion does not process for new transactions but remains editable and may later be reactivated.

An archived promotion does not process for new transactions but remains available for administrative and historical purposes.

### 11.2 Date validity

Not-yet-started/current/expired status is derived from `starts_at`, `ends_at`, and current time.

There is no administrator-settable `expired` field.

An expired promotion remains editable.

### 11.3 Redemption capacity

Available/exhausted redemption capacity is derived from configured limits and successful redemption history.

There is no administrator-settable `exhausted` field.

The contract does not allow callers to directly set:

```text
redemptions_used
remaining_redemptions
```

### 11.4 Code reservation

Active, inactive, expired, and redemption-capacity-exhausted promotions continue to reserve their normalized code.

Archived promotions release their normalized code.

Hard-deleted promotions release their normalized code.

If promotion A is archived and releases `SAVE20`, promotion B may subsequently reserve a code that normalizes to the same value.

If promotion A is then restored while promotion B reserves that normalized code, restoration must fail visibly and promotion A must remain archived.

The administrator may change A to an available code and then restore it.

Historical completed orders remain tied to their original economic effect even if a code is later reused.

### 11.5 Hard deletion

A promotion that has never been successfully redeemed may be hard-deleted when otherwise permitted.

A promotion that has been successfully redeemed may not be hard-deleted.

A redeemed promotion may instead be archived.

---

## 12. Create Semantics

Request:

```text
POST /admin/api/promotions
```

The request contains a complete valid promotion configuration.


### 12.1 Required and Optional Fields on Create

A create request must provide the following cross-cutting fields:

* `name`
* `type`
* `active`
* `archived`
* `activation`
* `eligibility`
* `map_override`

It must also provide every field identified as required for the selected promotion type in §10.

The following fields are optional unless required by the selected promotion type or by another supplied configuration:

* `code`
* `starts_at`
* `ends_at`
* `global_redemption_limit`
* `per_customer_redemption_limit`
* `stackable`
* `trigger_scope`
* `reward_scope`
* `percentage`
* `amount`
* `threshold`
* `trigger_quantity`
* `reward_quantity`
* `reward_limit`

Omitting an optional field on create means that the corresponding optional configuration is absent. The candidate must not be required to return omitted optional fields in any particular null-versus-omitted representation, provided GET and subsequent PATCH behavior preserve the same contract meaning.

`code` is required when `activation` is `"code"` and must be omitted or `null` when `activation` is `"automatic"`.

`stackable` is required when `activation` is `"code"`. For automatic promotions, `stackable` may be omitted or `null` because automatic promotions stack according to the Promotion Eval 2.0 business requirements rather than this setting.

Fields that are not applicable to the selected promotion type may be omitted or `null`. A candidate must not be required to persist or return meaningless type-specific configuration merely to satisfy a fixed response shape.

No unspecified default may change administrator intent. In particular, the evaluator must not assume a default value for a required field that the create request omitted; omission of a required field is an invalid create request.



A successful create:

- returns a 2xx status;
- returns JSON;
- returns an opaque promotion `id`;
- returns the effective administrative configuration necessary for contract-level round-trip verification.

The exact successful status code is not graded beyond being 2xx.

Example request:

```json
{
  "name":"Fall Thermometer Sale",
  "type":"percentage_off_product",
  "active":true,
  "archived":false,
  "activation":"automatic",
  "eligibility":{"mode":"everyone"},
  "map_override":false,
  "percentage":"10",
  "reward_scope":{
    "mode":"sku",
    "skus":["TH-0950"]
  }
}
```

The candidate may include additional non-conflicting response metadata.

---

## 13. Read Semantics

Request:

```text
GET /admin/api/promotions/{id}
```

A successful read:

- returns a 2xx status;
- returns JSON;
- returns the current administrative configuration;
- preserves the contract meanings and values required for round-trip verification.

Candidate-specific derived informational fields may be returned in addition to contract fields. The evaluator does not depend on undocumented derived fields.

Returned values must use the representations defined in §5–§9. They are compared by meaning, not as an exact echo of the submitted strings: for example, equal decimal values, the same instant expressed with a different UTC offset, and the same scope or eligibility values in a different order are equivalent.

The read endpoint represents current promotion administration state, not completed-order historical snapshots.

---

## 14. PATCH Semantics

Request:

```text
PATCH /admin/api/promotions/{id}
```

PATCH is partial.

### 14.1 Omitted field

An omitted field means:

> Leave its existing value unchanged.

Example:

```json
{
  "active":false
}
```

changes `active` only.

### 14.2 Explicit null

For a nullable optional field, explicit `null` means:

> Clear/remove the currently configured value.

Example:

```json
{
  "ends_at":null
}
```

removes the end date.

Example:

```json
{
  "global_redemption_limit":null
}
```

removes the global redemption limit.

### 14.3 Required values

A required field cannot be cleared or changed in a way that leaves the promotion structurally invalid.

Such an update must be rejected atomically.

### 14.4 Archive and restore

Archive:

```json
{
  "archived":true
}
```

Restore:

```json
{
  "archived":false
}
```

No separate archive/restore endpoint is required.

---

## 15. Delete Semantics

Request:

```text
DELETE /admin/api/promotions/{id}
```

A permitted hard deletion returns a 2xx status.

The exact successful status code is not graded.

A prohibited deletion returns a non-2xx error and leaves the promotion intact.

A successfully redeemed promotion must reject hard deletion.

---

## 15A. Completed-Order Reconciliation

Northstar must be able to emit a stable, machine-readable representation of the economic facts of each completed order, including the realized effect of promotions, for downstream accounting and reconciliation.

This is an observation boundary only. It does not prescribe how order, promotion, or historical data is stored, modeled, allocated, calculated, or persisted.

Request:

```text
GET /admin/api/orders/{order_id}/reconciliation
```

`{order_id}` is Northstar's existing completed-order identifier (the identifier in the order confirmation route). The operation uses the administrator authentication of §4 and the error contract of §17; an unknown order is a rejected operation.

A successful read returns a 2xx status and a JSON object with these fields:

| Field | JSON representation | Meaning |
|---|---|---|
| `order_id` | integer | The completed order |
| `lines` | array of line objects | One per purchased SKU |
| `lines[].sku` | string | Exact SKU purchased |
| `lines[].quantity` | positive integer | Units purchased |
| `lines[].unit_price` | decimal-dollar string | Unit selling price at purchase, before promotions |
| `merchandise_before_promotions` | decimal-dollar string | Merchandise before promotions |
| `merchandise_discount` | decimal-dollar string | Realized promotion reduction of merchandise |
| `merchandise_after_promotions` | decimal-dollar string | Merchandise charged |
| `shipping_discount` | decimal-dollar string | Shipping waived by promotion; `"0.00"` if none |
| `shipping` | decimal-dollar string | Shipping charged |
| `tax` | decimal-dollar string | Tax charged |
| `total` | decimal-dollar string | Final amount charged |
| `promotion_ids` | array of promotion identifiers | The §3 identifiers of the promotions applied to the order; empty if none |

Values use the representations of §5. The representation must satisfy:

- `merchandise_before_promotions` equals the sum of `unit_price × quantity` over `lines`;
- `merchandise_after_promotions` equals `merchandise_before_promotions − merchandise_discount`;
- `total` equals `merchandise_after_promotions + shipping + tax` and is the amount charged for the order.

`promotion_ids` lists the promotions **applied** to the completed transaction: those that, at authoritative checkout, qualified under the promotion rules and participated in calculating the transaction, whether automatic or code-activated. An applied promotion is listed even when MAP, the zero-price floor, or another pricing constraint limited its realized economic effect, including to zero. A code that was associated with the cart but whose promotion was not applied at checkout is not listed. Because promotion identifiers are stable, a promotion that later reuses the same normalized code is distinguishable.

`merchandise_discount` and `shipping_discount` are realized transaction economics in aggregate. Per-line or per-promotion allocation of the realized discount is not required.

The representation describes the completed transaction. It does not change when current product prices or promotion definitions are later edited, deactivated, expired, archived, or otherwise changed.

---

## 16. Required Validation Behavior

The administration boundary must reject contradictory or structurally invalid configurations rather than silently guessing, coercing, or transforming administrator intent.

Invalid operations must not partially mutate the promotion.

Examples include, but are not limited to:

### 16.1 Automatic activation with a code

Invalid:

```json
{
  "activation":"automatic",
  "code":"SAVE20"
}
```

### 16.2 Code activation without a code

Invalid:

```json
{
  "activation":"code",
  "code":null
}
```

### 16.3 Mixed scope modes

Invalid: a scope object that contains `skus` together with any of `brands`, `categories`, or `subcategories`,
whatever its `mode`.

### 16.4 Contradictory eligibility

Invalid:

```json
{
  "mode":"everyone",
  "levels":["vip"]
}
```

### 16.5 Missing type-specific requirement

A `percentage_off_product` configuration without `percentage` is invalid.

### 16.6 Invalid quantity or limit

Zero or negative quantities and configured redemption limits are invalid.

### 16.7 Invalid timestamp

A naive timestamp without an explicit offset is invalid.

### 16.8 Invalid Free Product activation

A `free_product` configured with `"activation":"automatic"` is invalid.

### 16.9 Invalid hard deletion

Hard deletion of a successfully redeemed promotion is invalid.

### 16.10 Invalid restoration

Restoring an archived coded promotion while another promotion reserves the same normalized code is invalid.

---

## 17. Error Contract

A rejected contract operation returns:

1. a non-2xx HTTP status;
2. a JSON body;
3. a stable machine-readable `error` string;
4. optionally, a human-readable `message`.

Minimum response shape:

```json
{
  "error":"invalid_promotion",
  "message":"Optional human-readable explanation."
}
```

Exact human-readable wording is not prescribed.

A large universal error-code taxonomy is not required.

Candidates may use reasonable stable error codes such as:

```text
invalid_promotion
promotion_not_found
code_conflict
delete_not_allowed
authentication_required
```

The evaluator must not reject an otherwise conforming implementation merely because it uses a different reasonable machine-readable error taxonomy unless a specific error value is explicitly normative.

Success and rejection must always be machine-distinguishable.

Rejections by Northstar's existing authentication and CSRF protection are governed by §4 rather than this section.

---

## 18. Representative Examples

These examples communicate administrator intent. They do not reveal hidden fixture combinations, expected economic outcomes, grader assertions, implementation structure, or algorithms.

### 18.1 Percentage Off Product

```json
{
  "name":"Thermometer Week",
  "type":"percentage_off_product",
  "active":true,
  "archived":false,
  "activation":"automatic",
  "eligibility":{"mode":"everyone"},
  "map_override":false,
  "percentage":"35",
  "reward_scope":{
    "mode":"sku",
    "skus":["TH-0900","TH-0950"]
  }
}
```

### 18.2 Buy X → Get Y at N% Off → Limit Z

```json
{
  "name":"Buy Two Get One Half Off",
  "type":"buy_x_get_y_percentage_off",
  "active":true,
  "archived":false,
  "activation":"automatic",
  "eligibility":{"mode":"everyone"},
  "map_override":false,
  "trigger_scope":{
    "mode":"sku",
    "skus":["TH-0900"]
  },
  "trigger_quantity":2,
  "reward_scope":{
    "mode":"sku",
    "skus":["TH-0950"]
  },
  "reward_quantity":1,
  "percentage":"50",
  "reward_limit":2
}
```

### 18.3 Code-Triggered Order Promotion

```json
{
  "name":"Contractor October",
  "type":"percentage_off_order",
  "active":true,
  "archived":false,
  "activation":"code",
  "code":"CONTRACTOR15",
  "eligibility":{
    "mode":"customer_levels",
    "levels":["contractor"]
  },
  "stackable":true,
  "map_override":false,
  "global_redemption_limit":500,
  "per_customer_redemption_limit":1,
  "percentage":"15",
  "starts_at":"2026-10-01T00:00:00Z",
  "ends_at":"2026-10-31T23:59:59Z"
}
```

### 18.4 Free Product

```json
{
  "name":"Free Thermometer Code",
  "type":"free_product",
  "active":true,
  "archived":false,
  "activation":"code",
  "code":"FREETHERMO",
  "eligibility":{"mode":"everyone"},
  "map_override":false,
  "reward_scope":{
    "mode":"sku",
    "skus":["TH-0950"]
  }
}
```

---

## 19. Contract Conformance vs. Promotion Correctness

A successful administration response shows only that the operation was accepted at this boundary. The promotion
behavior required by the task must be implemented in Northstar itself; conformance to this contract does not by
itself satisfy it.

---

## 20. Evaluator Use of This Contract

The evaluator uses this contract to establish and change promotion state (create, read, PATCH, archive/restore,
delete) and to read completed-order reconciliation (§15A). Promotion behavior itself is then observed through
Northstar's ordinary storefront, checkout, and order outcomes, not through this contract (§19).

---

## 21. Contract Authority

This contract is authoritative for its external HTTP/JSON boundary. It defines how promotions are administered, not
promotion business semantics, which are defined by the task.

---

## 22. Contract 1.0 Summary

Contract 1.0 intentionally standardizes:

- HTTP transport, four required promotion routes, and the completed-order reconciliation read;
- ordinary Northstar administrator authentication/CSRF integration;
- field names;
- JSON types;
- exact enum values;
- exact SKU preservation;
- scope representations;
- eligibility representations;
- monetary wire format;
- percentage wire format;
- quantity/limit representation;
- date/time representation;
- create/read/PATCH/delete semantics;
- null versus omission semantics;
- lifecycle operations;
- code-reservation behavior;
- validation behavior;
- machine-distinguishable success and failure.

It intentionally does **not** standardize:

- internal data model;
- persistence technology;
- ORM;
- code architecture;
- promotion algorithms;
- MAP reconciliation algorithm;
- stacking algorithm;
- concurrency implementation;
- transaction/locking strategy;
- promotion-processing order;
- administration UI design.

> **Hide the test cases, not the rules.**

> **We standardize the observable boundary, not the solution behind it.**
