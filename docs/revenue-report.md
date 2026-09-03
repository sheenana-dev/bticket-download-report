# Subscription Revenue Report

Automated revenue reporting for B-Ticket in-app subscriptions/purchases across
App Store, Google Play and Huawei AppGallery. Lives in `src/revenue/`, shares
config, Telegram and retry code with the download report.

## Two tiers — don't mix them up

| | Daily estimate | Monthly reconciled |
|---|---|---|
| Runs | every day with the download report (`daily_report.yml`) | 6th of month 09:07 PHT (`monthly_revenue.yml`) |
| Output | bilingual Telegram text → download group | 2-page PDF (EN page, JA page) + caption → `REVENUE_MONTHLY_CHAT_ID` (CEO chat) |
| Apple | Sales report DAILY — `Developer Proceeds × Units` is real net | Sales report MONTHLY — Apple's own roll-up |
| Google | estimated sales report — net = (charged − tax) × (1 − fee) | earnings report ledger — real fee/tax/refund lines = payout |
| Huawei | IAP export × (1 − fee) | same (Huawei exposes no ledger) — flagged "Estimate" in the PDF |
| Stored in | `data/revenue.csv` | `data/revenue_monthly.csv` |

All figures in PHP. Non-PHP lines are converted at ECB reference rates
(Frankfurter API, cached per day in `data/fx_cache.json`). Pin a treasury rate
with `REVENUE_FX_OVERRIDES=USD:56.20,CNY:7.80` and the API is skipped.

The daily job re-fetches the trailing 7 days every run, so Google's 3–7 day
lag and Apple's revisions self-heal into the CSV (upsert, later fetch wins).

## Commands

```bash
python -m src.revenue.main daily   --dry-run            # yesterday, no Telegram
python -m src.revenue.main daily   --date 2026-09-01    # specific day
python -m src.revenue.main monthly --dry-run            # previous month → reports/*.pdf
python -m src.revenue.main monthly --month 2026-08
python -m src.revenue.main probe   apple|google|huawei  # dump raw export headers/rows
```

## First-time setup checklist

1. **Apple** — the existing key works if it has the *Sales and Reports* (or
   Finance) role. `probe apple` should list rows with Product Type `IAY`/`IA1`.
2. **Google** — the service account already reads `stats/installs/`; it needs
   read on `sales/` and `earnings/` in the same bucket (Play Console → Users &
   permissions → *View financial data*). `probe google` prints both.
3. **Huawei** — three things Huawei's public docs get wrong or omit (verified
   via the AGC API Explorer, Sep 2026):
   - endpoint is `.../v1/IAPExport/{appId}` and needs `currency`, `timeType`,
     `exportType` query params;
   - a `uid` header carrying the **Developer ID** (Users and permissions →
     Personal information) is mandatory — without it every call is
     `403 client token authorization fail`, whatever the client's role;
   - it only works with a **team-level** API client (Project = N/A), not a
     project-scoped one. `HUAWEI_APP_ID` must be the *live* app's ID
     (Apps → app → App information), not an old draft's.
   Set `HUAWEI_UID`; defaults for path/columns/currency already match the
   real export. `probe huawei --date <a day with a sale>` prints the CSV.
4. **GitHub** — add secrets `HUAWEI_CLIENT_ID`, `HUAWEI_CLIENT_SECRET`,
   `HUAWEI_APP_ID`, `HUAWEI_UID`, and `REVENUE_MONTHLY_CHAT_ID` (the private
   chat the monthly PDF goes to — see below). Optional
   `REVENUE_TELEGRAM_CHAT_ID` moves the daily text off the download group.
   Repo *variables* hold any `REVENUE_*` fee/FX overrides.

   **Getting a private chat id**: Telegram bots cannot message a person
   first. The recipient opens the bot and sends `/start`; then
   `curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates" | grep -o '"chat":{"id":[0-9-]*'`
   shows their id (positive number for a person, negative for a group).
5. Trigger `Monthly Revenue Report (PDF)` manually with `month=2026-08` to get
   the first PDF and seed `revenue_monthly.csv` (MoM needs two months).

## Fee rates

`REVENUE_GOOGLE_FEE_RATE` (default 0.15) and `REVENUE_HUAWEI_FEE_RATE`
(default 0.15) only affect the *daily estimate*. Google's monthly number comes
from actual fee lines. If B-Ticket is not in Play's 15% tier for any SKU, the
daily estimate will run slightly high — the monthly PDF is the number to quote.

## Fonts (PDF)

Poppins-Bold (brand) and DejaVu Sans (numbers — Helvetica has no ₱ glyph)
are bundled in `assets/fonts/`, so the PDF renders identically on a Mac and
on the runner. Japanese uses IPA Gothic, installed on the runner via `apt`;
without it the PDF falls back to reportlab's built-in CID font, which renders
in Preview/Telegram but not in every viewer.

`monthly` also back-fills every day of its month into `data/revenue.csv`
(skip with `--skip-daily-backfill`) so the daily chart is populated from the
first PDF.
