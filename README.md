# Asset Leasing

Equipment and plant hire lifecycle for ERPNext v16 — lessor side, for ERT heavy
equipment rental.

Built as a standalone Frappe app so the entire configuration is version
controlled and reproducible. Nothing is configured through the user interface.

## Status

**P0 complete — foundations only.** This app does not yet manage rentals.

| Phase | Scope | State |
|---|---|---|
| P0 | Site, app, Git, roles, Settings, price list | done |
| P1 | `al_` custom fields on Asset and related DocTypes | not started |
| P2 | Rental Agreement, availability, pricing | not started |
| P3 | Dispatch, Asset Movement integration | not started |
| P4 | Return, inspection, damage, billing | not started |
| P5 | Downtime, deposits, overdue | not started |
| P6 | Long-term contracts via Subscription | not started |
| P7–P9 | Reports, dashboard, notifications, tests | not started |

## Pricing — read before implementing anything

The confirmed commercial rule is a **fixed monthly rate** (INR 45,000 for the
Excavator EX-200). Sub-month hires bill **pro rata derived from it**.

This is **not** a tiered model. There are deliberately no daily or weekly price
lists, no duration bands and no tier-selection engine.

Five policy decisions remain **unanswered by the client** and are not guessed:

| Ref | Decision |
|---|---|
| Q-14 | Divide the monthly rate by a fixed 30, or by actual days in the calendar month? |
| Q-15 | Is there a minimum rental period? |
| Q-16 | How are part-day rentals calculated? |
| Q-17 | How is a hire crossing a calendar month handled? |
| Q-18 | Is the monthly rate a cap for a period of one month or less? |

`asset_leasing/rental/pricing.py` raises `PricingPolicyNotConfigured` rather
than assuming any of them. Record the answers in **Asset Leasing Settings** and
tick *Pricing Policy Confirmed* to enable calculation.

Q-14 is commercially material: at a fixed divisor of 30 a full January bills
INR 46,500 and a full February INR 42,000, against a monthly rate of 45,000.

## Install

```bash
bench get-app git@github.com:sufiyanbuild/asset-leasing-erpnext.git
bench --site <site> install-app asset_leasing
```

Requires ERPNext (declared in `required_apps`).

## Conventions

- Custom fields on standard DocTypes are prefixed `al_`
- Server logic lives in the app, never in Server Script records
- Client scripts ship as `.js` files, never as Client Script records
- All configuration ships as fixtures; run
  `bench --site <site> export-fixtures --app asset_leasing` after any change

## Licence

MIT
