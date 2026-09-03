# Subscription Revenue Report

Automated revenue reporting for B-Ticket in-app subscriptions/purchases across
App Store, Google Play and Huawei AppGallery. Lives in `src/revenue/`, shares
config, Telegram and retry code with the download report.

## Two tiers — don't mix them up

| | Daily estimate | Monthly reconciled |
|---|---|---|
| Runs | every day with the download report (`daily_report.yml`) | 6th of month 09:07 PHT (`monthly_revenue.yml`) |
| Output | bilingual Telegram text | one-page PDF (EN + JP exec summary) + Telegram caption |
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
3. **Huawei** — run `probe huawei`. If it 404s, the export path differs for
   your region: check AppGallery Connect → Reports → In-app payment report →
   API reference and set `HUAWEI_IAP_REPORT_PATH`. Then set
   `HUAWEI_IAP_AMOUNT_COLUMN` / `HUAWEI_IAP_COUNT_COLUMN` to the exact CSV
   headers you see, and `HUAWEI_IAP_CURRENCY` (settlement currency).
4. **GitHub** — add secrets `HUAWEI_CLIENT_ID`, `HUAWEI_CLIENT_SECRET`,
   `HUAWEI_APP_ID` (optional `REVENUE_TELEGRAM_CHAT_ID` for a finance-only
   group) and repo *variables* for any `HUAWEI_IAP_*` / `REVENUE_*` overrides.
5. Trigger `Monthly Revenue Report (PDF)` manually with `month=2026-08` to get
   the first PDF and seed `revenue_monthly.csv` (MoM needs two months).

## Fee rates

`REVENUE_GOOGLE_FEE_RATE` (default 0.15) and `REVENUE_HUAWEI_FEE_RATE`
(default 0.15) only affect the *daily estimate*. Google's monthly number comes
from actual fee lines. If B-Ticket is not in Play's 15% tier for any SKU, the
daily estimate will run slightly high — the monthly PDF is the number to quote.

## Fonts (PDF)

Poppins-Bold (brand) is bundled in `assets/fonts/`. Numbers use DejaVu Sans
(Helvetica has no ₱). Japanese uses IPA Gothic, installed on the runner via
`apt`; without it the PDF falls back to reportlab's built-in CID font, which
renders in Preview/Telegram but not in every viewer.
