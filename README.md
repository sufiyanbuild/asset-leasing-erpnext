# Asset Leasing

Equipment and plant hire for ERPNext v16, lessor side, built for ERT heavy
equipment rental. Covers short-term hire billed on actual duration and
long-term contracts billed monthly.

A standalone Frappe app: the whole configuration is version-controlled and
reproducible, and nothing is configured through the user interface.

## What it does

| Area | Documents and behaviour |
|---|---|
| Fleet | Rentable **Asset** with rental charge item, home yard, operational status (Available, Reserved, On Hire, In Transit, Under Inspection, Under Repair, Retired), meter and compliance dates |
| Booking | **Rental Agreement** with approval workflow, double-booking prevention, credit and hire-block checks, quotation conversion, and an equipment picker that labels booked machines |
| Out | **Rental Dispatch**: one standard Asset Movement (Transfer), machine On Hire, gate pass, safety checks (expired insurance, fitness or permit; open repairs; overdue maintenance) |
| On site | Site-to-site transfer; **Rental Downtime Log** with manager approval |
| Back | **Rental Return** with an inspection workflow; damage approved by a manager; repair jobs; off-hire note |
| Billing | Draft Sales Invoices for rent, damage recovery and transport; long-term contracts through a standard ERPNext Subscription; security deposits on Payment Entry |
| Control | Daily jobs for overdue returns, compliance expiry, utilisation and status reconciliation; nine notifications; ten reports; the Asset Leasing Overview dashboard and workspace |

All invoices are raised as drafts for Finance to review. Rent is identified by
`Sales Invoice Item.al_asset` and billed through a non-stock service item; the
core `asset` field, which ERPNext reads as a disposal, is never used.

## Pricing

A fixed **monthly rate** is the only commercial rate; hires shorter than a month
are billed pro rata from it. There are no daily or weekly price lists and no
tier engine.

The pro-rata policy confirmed by the client (Q-14 to Q-18) is recorded in
**Asset Leasing Settings** on install:

| Ref | Decision |
|---|---|
| Q-14 | Divide by the actual number of days in the calendar month |
| Q-15 | No minimum rental period (transport, damage and deposits are settled separately) |
| Q-16 | Round up: any part of a day is a full day |
| Q-17 | One divisor for the whole hire: the month in which the hire starts |
| Q-18 | No cap: a hire of a month or less may bill above the monthly rate |

Worked example at INR 45,000 a month: ten days starting in January bill
INR 14,516.13, the same ten days starting in February INR 16,071.43, and any
full calendar month INR 45,000. Calculations live in
`asset_leasing/rental/pricing.py` and read the recorded settings; if a site has
no confirmed policy, no rent is calculated and returns record
*Awaiting Pricing Policy*.

Long-term contracts must end on a monthly billing boundary; the Subscription
bills the full monthly rate for each period.

## Install

```bash
bench get-app git@github.com:sufiyanbuild/asset-leasing-erpnext.git
bench --site <site> install-app asset_leasing
bench --site <site> migrate
```

Requires ERPNext (declared in `required_apps`) and Python 3.14, matching
Frappe v16. After installing, set in **Asset Leasing Settings**:

- Damage Recovery Item and Transport Charge Item (non-stock service items)
- Security Deposit Liability Account (a Liability ledger with no account type)
- Default Yard Location (optional)

Give each machine a rental charge item with a price on the **Rental - Monthly**
price list, and set the Location Type on yards and customer sites.

## Tests

```bash
bench --site <site> set-config allow_tests true
bench --site <site> run-tests --app asset_leasing
```

The tests build their own company and masters and roll everything back.

## Conventions

- Custom fields on standard DocTypes are prefixed `al_`
- Server logic lives in the app, never in Server Script records
- Client scripts ship as `.js` files, never as Client Script records
- Custom fields, roles and workflows ship as fixtures; run
  `bench --site <site> export-fixtures --app asset_leasing` after changing them
- Reports, print formats, notifications, number cards, charts, the dashboard and
  the workspace are standard records in the module folder
- Role permissions on standard DocTypes are applied by `setup/permissions.py`
  on install and migrate, never shipped as a Custom DocPerm fixture

## Licence

MIT
