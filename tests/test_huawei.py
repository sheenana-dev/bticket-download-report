from datetime import date

import responses

from src.stores.huawei import HuaweiClient, TOKEN_URL, REPORT_URL

SAMPLE_CSV = (
    "\ufeffDate,Valid impressions,Valid impression CTR,Details UV (reported by client),"
    "Total downloads,Successful updates,New downloads,Details page conversion rate,"
    "Successful installs,Installation success rate,Uninstalls,Sharings,Icon clicks,"
    "New installs,Total uninstalls\n"
    "20260210,5,10.00%,20,890,10,890,50.00%,885,99.44%,3,0,0,885,5\n"
)

CSV_DOWNLOAD_URL = "https://example.huawei.com/report.csv"


@responses.activate
def test_fetch_report_success(huawei_config):
    # Mock token endpoint
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "test-token-123", "expires_in": 3600},
        status=200,
    )

    # Mock report endpoint (returns fileURL)
    url = REPORT_URL.format(app_id=huawei_config.app_id)
    responses.add(
        responses.GET,
        url,
        json={"fileURL": CSV_DOWNLOAD_URL, "ret": {"code": 0, "msg": "success"}},
        status=200,
    )

    # Mock CSV download
    responses.add(
        responses.GET,
        CSV_DOWNLOAD_URL,
        body=SAMPLE_CSV,
        status=200,
    )

    client = HuaweiClient(huawei_config)
    result = client.fetch_report(date(2026, 2, 10))

    assert result.store_name == "Huawei"
    assert result.daily_downloads == 890
    assert result.total_downloads is None  # cumulative tracked in main.py
    assert result.error_message is None
    assert result.data_date == "Feb 10"


@responses.activate
def test_fetch_report_auth_failure(huawei_config):
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"error": "invalid_client"},
        status=401,
    )

    client = HuaweiClient(huawei_config)
    result = client.fetch_report(date(2026, 2, 10))

    assert result.store_name == "Huawei"
    assert result.daily_downloads is None
    assert result.error_message is not None


@responses.activate
def test_fetch_report_no_data_for_date(huawei_config):
    responses.add(
        responses.POST,
        TOKEN_URL,
        json={"access_token": "test-token-123", "expires_in": 3600},
        status=200,
    )

    url = REPORT_URL.format(app_id=huawei_config.app_id)
    responses.add(
        responses.GET,
        url,
        json={"ret": {"code": 0, "msg": "success"}},
        status=200,
    )

    client = HuaweiClient(huawei_config)
    result = client.fetch_report(date(2026, 2, 10))

    assert result.store_name == "Huawei"
    assert result.daily_downloads is None
    assert "delayed" in (result.data_date or "")
