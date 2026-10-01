# Promotion Eval 2.0 — Task

## Objective

Extend the existing Northstar Outdoor Living application with a production-quality promotion system.

The system must support the promotion behavior described below, integrate with Northstar's existing cart and checkout flows, remain administratively usable through Northstar, and implement the programmatic administration boundary defined in `PROMOTION_ADMINISTRATION_INTEROPERABILITY_CONTRACT.md`.

Northstar is an existing application. Unless this task explicitly requires otherwise, preserve its existing behavior and established interfaces. You may refactor or extend the implementation as needed, but existing consumers should continue to function without modification.

## Promotion Model

A promotion has a promotion type and may also define applicable configuration such as active/inactive and archival state, optional start and end times, automatic or code-triggered activation, customer eligibility, redemption limits, code-promotion stackability, MAP override permission, product scopes, and type-specific quantities, thresholds, percentages, or fixed amounts.

The required administration fields and wire representations are defined by the Promotion Administration Interoperability Contract.

### Product scopes

A product scope uses one of two targeting modes:

- **Explicit SKU:** one or more specific SKUs.
- **Attribute filters:** Brand, Category, and/or Subcategory. Multiple values within the same attribute level use OR; populated attribute levels combine using AND; omitted levels impose no restriction.

Where both Trigger Scope and Reward Scope exist, they are independent and may overlap or differ. Qualifying quantities may aggregate across SKUs that match the applicable scope.

## Required Promotion Types

Implement all eleven promotion mechanisms.

### 1. Percentage Off Product
Reduce each qualifying product unit by the configured percentage. The discount operates at the individual-unit level.

### 2. Fixed Amount Off Product
Reduce each qualifying product unit by the configured fixed amount.

### 3. Percentage Off Order
The promotion may optionally require merchandise matching a Trigger Scope. Once qualified, the configured percentage applies to the order's merchandise.

### 4. Fixed Amount Off Order
The promotion may optionally require merchandise matching a Trigger Scope. Once qualified, the configured fixed amount applies across eligible merchandise. Any portion that cannot be realized is forfeited.

### 5. Spend Threshold → Fixed Amount Off Order
Require a merchandise spending threshold, optionally limited to a Trigger Scope. Qualification uses the applicable pre-promotion merchandise subtotal. Once qualified, apply the configured fixed order benefit.

### 6. Spend Threshold → Percentage Off Order
Require a merchandise spending threshold, optionally limited to a Trigger Scope. Qualification uses the applicable pre-promotion merchandise subtotal. Once qualified, apply the configured percentage to the order's merchandise.

### 7. Buy X → Get Y at N% Off → Limit Z
This promotion defines a Trigger Scope and quantity X, a Reward Scope and quantity Y, a reward percentage N, and a maximum number of rewarded units Z per order.

Trigger quantities may aggregate across matching SKUs. Reward products must already be present in the cart; the promotion does not add merchandise or quantities. Reward units cannot also serve as trigger units for the same promotion.

When more eligible reward units are available than may receive the reward, use the lowest-priced eligible units. Economically equivalent choices are acceptable at an equal-price boundary. N may be 100%, producing a free reward unit. The reward percentage applies to each rewarded unit.

### 8. Buy X Product → Fixed Amount Off Order
Require at least X units matching Trigger Scope. Qualifying quantities may aggregate across matching SKUs. X is a qualification trigger, not a repeating benefit. Once qualified, apply the configured fixed order benefit.

### 9. Buy X Product → Percentage Off Order
Require at least X units matching Trigger Scope. Qualifying quantities may aggregate across matching SKUs. X is a qualification trigger, not a repeating benefit. Once qualified, apply the configured percentage order benefit.

### 10. Free Product
Free Product is code-triggered only. When qualified, exactly one eligible Reward Scope unit already in the cart is free. Do not automatically add merchandise or increase cart quantity. No separate trigger product is required.

When more than one eligible unit could receive the reward, use the lowest-priced eligible unit. Economically equivalent choices are acceptable at an equal-price boundary.

### 11. Free Shipping
Waive the otherwise-applicable shipping charge when qualified. Qualification may use activation and eligibility alone, a Trigger Scope, a merchandise threshold, or a Trigger Scope together with a merchandise threshold. A scoped threshold counts only merchandise in that scope.

## Promotion Economics and Stacking

Promotion qualification and nominal benefits use a common pre-promotion merchandise state. A promotion's own benefit does not change whether it qualifies, and stacked promotions do not sequentially change the calculation basis for other promotions.

All qualifying automatic promotions stack. Multiple stackable code-triggered promotions may coexist. A newly accepted non-stackable code replaces a previously associated incompatible non-stackable code. Automatic promotions continue to participate according to their ordinary rules.

The order in which promotions are processed must not change the economic result.

Promotion discounts may reduce merchandise to zero, but never below zero. Unusable fixed discount value is forfeited rather than refunded, credited, or carried forward.

### MAP

Northstar products may be MAP-enforced. Each promotion specifies whether it may override MAP.

A promotion without MAP override permission may not cause a MAP-enforced product's effective merchandise price to fall below MAP. A promotion with MAP override permission may contribute discount below MAP.

For stacked promotions, enforce the promotions' MAP permissions against the combined economic result and realize the maximum combined discount legally permitted by those permissions and the zero-price floor. The result must remain independent of promotion processing order.

MAP is an internal pricing constraint. Customers do not need to see MAP values or internal discount allocation, but if pricing restrictions prevent the full promotion benefit from being realized, provide a meaningful customer-facing indication that product discount restrictions limited the promotion.

## Promotion Codes

Promotion codes are case-insensitive and formatting-insensitive. Normalize codes by lowercasing and removing whitespace and punctuation while retaining letters and numbers. Normalized codes must be unique among promotions that currently reserve a code.

Invalid, inactive, expired, customer-ineligible, or already-exhausted codes are rejected with useful customer-facing feedback.

An otherwise-valid code is accepted and associated with the cart even if the cart does not yet satisfy its product, quantity, or spending qualification. Association does not reserve redemption capacity. Whether an associated promotion applies is determined at authoritative checkout.

An associated code remains associated if its promotion later stops producing a benefit because of qualification, eligibility, date/lifecycle, or redemption-capacity changes. Association remains tied to the specific promotion originally accepted, even if its code is later released and reused.

Customers must be able to enter and clear promotion codes from the cart using ordinary browser form behavior without requiring JavaScript. Implement the following cart-page interoperability markers:

- `data-promotion-code-input` on the text-capable HTML `<input>` for the code;
- `data-promotion-code-submit` on the submit control;
- `data-promotion-code-status="accepted"` or `"rejected"` on the customer-visible result of the latest submission;
- one `data-promotion-code-associated="<code>"` element for each currently associated code promotion;
- `data-promotion-code-clear` on a normally activatable button or submit control that clears all associated code promotions without affecting automatic promotions; it must be present whenever at least one code promotion is associated.

## Customer Eligibility

Promotions may apply to everyone, one or more Northstar customer levels (`retail`, `contractor`, `vip`), or one or more specific registered customers.

Guests may use generally eligible promotions and codes, but cannot qualify for promotions that require identity as a particular registered customer. Guests do not have a promotion customer level; a level-restricted promotion requires a registered customer with one of its levels. Eligibility is authoritative at checkout.

## Cart Login and Code Association

Existing Northstar guest-to-customer cart behavior must continue to work with promotions.

Successfully associated codes from the guest cart and any existing customer cart carry into the resulting authenticated cart and remain subject to the ordinary promotion, stacking, eligibility, lifecycle, capacity, and checkout rules.

If a guest cart is merged into an existing customer cart and each contains an otherwise-valid non-stackable code that cannot coexist, retain the code already associated with the customer's existing cart and drop the conflicting guest-cart code.

## Dates, Revalidation, and Checkout

Promotions may have optional start/end validity in addition to independent active/inactive state. A promotion must be active and currently within its configured validity period to be newly accepted or applied.

Promotion results shown in the cart are provisional. Revalidate promotions at checkout using the current promotion definition and current checkout state.

If revalidation changes the amount the customer would be charged from the amount previously presented or confirmed for that checkout, present the updated terms and require confirmation rather than silently completing at the changed amount. When the checkout form is re-presented with the updated terms, its ordinary resubmission (without JavaScript) counts as that confirmation.

Once an existing Northstar checkout attempt has legitimately fixed its monetary terms, a later change may allow that attempt to complete at those fixed terms or cause it to be refused, but it must not silently complete at a different amount.

Completed checkout freezes the historical economic result.

## Redemption Limits

Support optional global redemption limits, per-customer redemption limits, or both. When both are configured, both must have remaining capacity.

A promotion consumes one applicable redemption when it is applied to a successfully completed checkout, including when pricing constraints reduce its realized economic effect to zero.

Per-customer limits require a known registered customer identity. A promotion with a per-customer redemption limit cannot be used by a guest.

## Tax, Shipping, and Rounding

Northstar's tax rate remains 8.25%. Tax is calculated on taxable merchandise actually paid after promotion discounts. Shipping is not taxable.

Promotion spending thresholds use qualifying pre-promotion merchandise subtotal. Shipping and tax do not count toward those thresholds.

Northstar's ordinary customer-level free-shipping threshold is evaluated using the post-promotion merchandise subtotal. A qualifying Free Shipping promotion may independently waive the resulting shipping charge.

Monetary calculations that require cent rounding use round-half-up to the cent.

## Promotion Lifecycle and Code Namespace

Administrative lifecycle, date validity, and redemption capacity are separate concepts.

Inactive promotions do not process for new transactions but remain editable and may later be reactivated. Archived promotions do not process for new transactions but remain available for administration and historical integrity.

Active, inactive, expired, and redemption-exhausted promotions continue to reserve their normalized code. Archived and hard-deleted promotions release it.

If restoring an archived promotion would conflict with a normalized code currently reserved by another promotion, restoration must fail visibly and the archived promotion must remain archived.

A promotion that has never been successfully redeemed may be hard-deleted. A successfully redeemed promotion may not be hard-deleted, but may be archived.

## Historical Integrity and Reconciliation

Completed orders must preserve the economics of the transaction. Later changes to products or promotions must not recalculate or alter completed orders.

Implement the completed-order reconciliation interface defined by the Promotion Administration Interoperability Contract. Its output must remain stable for a completed order even when current product prices, promotion definitions, lifecycle state, or code usage later change.

## Administration

Promotion behavior must be manageable by an authenticated Northstar administrator and through the required HTTP/JSON interface in `PROMOTION_ADMINISTRATION_INTEROPERABILITY_CONTRACT.md`.

That contract is authoritative for the programmatic administration boundary, including routes, fields, wire representations, validation, PATCH semantics, lifecycle operations, and completed-order reconciliation.

Administration must use Northstar's existing administrator authentication and CSRF protections. Do not introduce evaluator-only credentials or privileged bypasses.

The administration UI must remain usable, but no particular page layout or visual design is required.

## Customer-Facing Behavior

Customers must be able to understand the promotion result sufficiently for normal use, including the resulting merchandise subtotal/discount, shipping, tax, and total.

Promotion-code failures and material pricing restrictions must provide useful feedback. Exact wording and visual design are not prescribed.

## Existing Northstar Guarantees

The promotion system must preserve Northstar's existing behavior and interfaces except where this task explicitly changes transaction economics.

In particular, promotions must integrate correctly with Northstar's existing checkout, inventory, idempotency, concurrency, payment, recovery, cart persistence/merge, product activation, and completed-order behavior. Promotion redemption state must remain consistent with the authoritative completed-order outcome.

## Implementation Freedom

You may choose the internal database schema, models, services, modules, algorithms, numeric representation, persistence design, transaction and locking strategy, promotion-processing implementation, discount allocation, and UI structure.

The required outcomes and candidate-visible interfaces are the contract. No particular internal architecture is required.
