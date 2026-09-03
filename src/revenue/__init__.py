"""Subscription / in-app revenue reporting for B-Ticket.

Two tiers of numbers, deliberately kept apart:

* **Daily estimate** — pulled from each store's transaction-level export the
  day after (Apple Sales report, Google Play estimated sales report, Huawei IAP
  report), converted to PHP at the day's FX rate. Good for trend-watching;
  Google/Huawei net is *estimated* by applying a fee rate.
* **Monthly reconciled** — Apple's MONTHLY sales report (developer proceeds)
  and Google's earnings report (real fee/tax/refund lines in merchant
  currency). This is what should match the payouts.

Everything is persisted to ``data/revenue.csv`` (daily rows) and
``data/revenue_monthly.csv`` (reconciled rows) so the dashboard and future
reports read from one place.
"""
