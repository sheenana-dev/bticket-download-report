# Manual Google Play Refresh (freeze fallback)

Google Play install counts come **only** from the GCS bulk CSV export — there is
no API alternative (the Play Developer Reporting API has vitals only; Firebase
`first_open` undercounts massively for this app). When that export **freezes**
(as it did Jun 21 – Jul 7, 2026, stuck at Jun 17), this tool lets you refresh the
Google Play numbers by hand from the Play Console UI until Google resumes.

When the export resumes, the daily job's reconcile **auto-corrects** these manual
values to Google's official figures — so using this tool is safe and temporary.

## Get the numbers

Play Console → **Statistics** → metric **"device acquisition"** (daily new
installs). Either read the daily values off the table, or use the page's export.

## Run it

```bash
# Option A: paste DATE:COUNT pairs (plain integers, no thousands separators)
python scripts/refresh_google_play.py --pairs "2026-06-18:149,2026-06-19:153"

# Option B: a CSV export (auto-detects the Date column + first data column)
python scripts/refresh_google_play.py --csv play_export.csv
python scripts/refresh_google_play.py --csv play_export.csv --column "All countries / regions"
```

It merges the values into `data/downloads.csv` via the same `reconcile_history_rows`
path the daily report uses (cumulative totals rebuilt in date order), then prints
a **report preview**. Nothing is sent to Telegram.

## Deliver to the group

```bash
git add data/downloads.csv
git commit -m "chore: manual Google Play refresh"
git push
gh workflow run daily_report.yml   # or just wait for the scheduled run
```

The scheduled GitHub Actions run reads `data/downloads.csv` and delivers to the
Telegram group set by the `TELEGRAM_CHAT_ID` **secret** (not `.env`).

## Notes

- Metric caveat: "device acquisition" (new device installs) differs slightly from
  the export's "user installs" the report normally tracks; they reconcile to the
  official user-installs figures once Google's export catches up.
- This does not auto-update — re-run it whenever you want fresh numbers while the
  export is frozen.
