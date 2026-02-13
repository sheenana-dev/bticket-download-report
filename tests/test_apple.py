import gzip
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import responses

from src.stores.apple import AppleStoreClient

SAMPLE_TSV = (
    "Provider\tProvider Country\tSKU\tDeveloper\tTitle\tVersion\t"
    "Product Type Identifier\tUnits\tDeveloper Proceeds\tBegin Date\t"
    "End Date\tCustomer Currency\tCountry Code\tCurrency of Proceeds\t"
    "Apple Identifier\tCustomer Price\tPromo Code\tParent Identifier\t"
    "Subscription\tPeriod\tCategory\tCMB\tDevice\tSupported Platforms\t"
    "Proceeds Reason\tPreserved Pricing\tClient\tOrder Type\n"
    "APPLE\tUS\tcom.bticket.app\tDev\tB-Ticket\t1.0\t"
    "1F\t150\t0\t02/10/2026\t02/10/2026\tUSD\tUS\tUSD\t"
    "12345\t0\t\t\t\t\tTravel\t\tiPhone\tiOS\t\t\t\t\n"
    "APPLE\tPH\tcom.bticket.app\tDev\tB-Ticket\t1.0\t"
    "1F\t75\t0\t02/10/2026\t02/10/2026\tPHP\tPH\tUSD\t"
    "12345\t0\t\t\t\t\tTravel\t\tiPhone\tiOS\t\t\t\t\n"
    "APPLE\tUS\tcom.other.app\tDev\tOther\t1.0\t"
    "1F\t999\t0\t02/10/2026\t02/10/2026\tUSD\tUS\tUSD\t"
    "99999\t0\t\t\t\t\tGames\t\tiPhone\tiOS\t\t\t\t\n"
)


@responses.activate
@patch.object(AppleStoreClient, "_generate_jwt", return_value="mock-jwt-token")
def test_fetch_and_parse_success(mock_jwt, apple_config):
    gzipped = gzip.compress(SAMPLE_TSV.encode("utf-8"))
    responses.add(
        responses.GET,
        "https://api.appstoreconnect.apple.com/v1/salesReports",
        body=gzipped,
        status=200,
        content_type="application/a-gzip",
    )

    client = AppleStoreClient(apple_config)
    result = client.fetch_report(date(2026, 2, 10))

    assert result.store_name == "App Store"
    assert result.daily_downloads == 225  # 150 + 75 (only com.bticket.app rows)
    assert result.error_message is None
    assert result.data_date == "Feb 10"


@responses.activate
@patch.object(AppleStoreClient, "_generate_jwt", return_value="mock-jwt-token")
def test_fetch_api_error(mock_jwt, apple_config):
    responses.add(
        responses.GET,
        "https://api.appstoreconnect.apple.com/v1/salesReports",
        json={"errors": [{"detail": "Unauthorized"}]},
        status=401,
    )

    client = AppleStoreClient(apple_config)
    result = client.fetch_report(date(2026, 2, 10))

    assert result.store_name == "App Store"
    assert result.daily_downloads is None
    assert result.error_message is not None


def test_parse_tsv_filters_by_sku(apple_config):
    client = AppleStoreClient(apple_config)
    gzipped = gzip.compress(SAMPLE_TSV.encode("utf-8"))
    units = client._parse_tsv(gzipped)
    # Should only count com.bticket.app: 150 + 75 = 225
    assert units == 225
