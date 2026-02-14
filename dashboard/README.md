# 📊 B-Ticket Download Dashboard

A Streamlit dashboard for visualizing B-Ticket app download metrics across App Store and Google Play.

## Local Setup

```bash
cd dashboard
pip install -r requirements.txt
streamlit run app.py
```

The dashboard loads data from the GitHub repo by default. To use a local CSV:

```bash
export GITHUB_CSV_URL=""  # empty disables remote fetch
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GITHUB_CSV_URL` | `https://raw.githubusercontent.com/sheenana-dev/bticket-download-report/main/data/downloads.csv` | URL to fetch CSV data from |

## Deploy to Streamlit Cloud

1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Select the repo → Branch: `main` → Main file: `dashboard/app.py`
4. (Optional) Set `GITHUB_CSV_URL` in Streamlit secrets if using a different repo
5. Click **Deploy**

The dashboard auto-refreshes with each new CSV commit from the daily GitHub Actions workflow.
