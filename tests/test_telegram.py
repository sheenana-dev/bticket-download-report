from unittest.mock import patch

import responses

from src.telegram import send_telegram_message, TELEGRAM_API_URL


@responses.activate
def test_send_success(telegram_config):
    url = TELEGRAM_API_URL.format(token=telegram_config.bot_token)
    responses.add(
        responses.POST,
        url,
        json={"ok": True, "result": {"message_id": 1}},
        status=200,
    )

    result = send_telegram_message(telegram_config, "Test message")
    assert result is True


@responses.activate
def test_send_api_error_then_retry_success(telegram_config):
    url = TELEGRAM_API_URL.format(token=telegram_config.bot_token)

    # First call fails
    responses.add(
        responses.POST,
        url,
        json={"ok": False, "description": "Bad Request"},
        status=400,
    )
    # Second call succeeds
    responses.add(
        responses.POST,
        url,
        json={"ok": True, "result": {"message_id": 2}},
        status=200,
    )

    with patch("src.telegram.time.sleep"):  # Skip the 60s wait in tests
        result = send_telegram_message(telegram_config, "Test message")

    assert result is True


@responses.activate
def test_send_both_attempts_fail(telegram_config):
    url = TELEGRAM_API_URL.format(token=telegram_config.bot_token)

    responses.add(responses.POST, url, json={"ok": False}, status=500)
    responses.add(responses.POST, url, json={"ok": False}, status=500)

    with patch("src.telegram.time.sleep"):
        result = send_telegram_message(telegram_config, "Test message")

    assert result is False
