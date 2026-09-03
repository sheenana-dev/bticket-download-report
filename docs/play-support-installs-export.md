# Google Play Support — Installs Export Frozen

Filed because the Cloud Storage bulk **installs** export stalled at Jun 17, 2026
while other report types (crashes, ratings) stayed current. This blocks the
daily download report from updating Google Play numbers.

## How to send
1. Check the [Google Play Status Dashboard](https://status.play.google.com/) first — if there's an active reporting incident, just wait.
2. Play Console → **Help** (left nav, bottom) → contact form.
3. **Select a topic → Reporting.**
4. Paste the message below. Attach a screenshot of Statistics → User acquisition showing data past Jun 17.

## Message

> **Subject:** Cloud Storage bulk export — installs report frozen since June 21
>
> The Cloud Storage bulk export for **install statistics** has stopped updating for my developer account.
>
> - **Bucket:** `pubsite_prod_7245262499315294571`
> - **App:** `com.bticket.bticket` (also affects `com.betrnk.btickets`)
> - **File:** `stats/installs/installs_com.bticket.bticket_202606_overview.csv` was last modified **2026-06-21** and contains data only through **June 17**. No July (`202607`) installs file has been created.
>
> This is **isolated to the installs/acquisitions export** — other reports in the same bucket are current: `stats/crashes` was written July 1 (data through June 30) and `stats/ratings` was written July 1 (data through June 27). The Play Console Statistics UI also shows install/user-acquisition data past June 17, so the data exists but is not being written to the bulk export.
>
> Please investigate the installs/acquisitions bulk-report generation for this account and backfill June 18 onward. Thank you.

## Evidence (as of 2026-07-01)
| Report type | Last written by Google | Newest data |
|---|---|---|
| stats/crashes | Jul 1 | Jun 30 |
| stats/ratings | Jul 1 | Jun 27 |
| **stats/installs** | **Jun 21** | **Jun 17** |
| stats/store_performance | Jun 22 | ~Jun 22 |
