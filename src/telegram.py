import logging
import time

import requests

from src.config import TelegramConfig

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram_message(config: TelegramConfig, message: str) -> bool:
    """Send a message to the configured Telegram chat. Retries once after 60s on failure."""
    url = TELEGRAM_API_URL.format(token=config.bot_token)
    payload = {
        "chat_id": config.chat_id,
        "text": message,
        "parse_mode": "HTML",
    }

    for attempt in range(2):
        try:
            resp = requests.post(url, json=payload, timeout=30)
            data = resp.json()

            if resp.ok and data.get("ok"):
                logger.info("Telegram message sent successfully")
                return True

            logger.error(
                "Telegram API error (attempt %d): %s",
                attempt + 1, data.get("description", resp.text),
            )
        except requests.RequestException as e:
            logger.error("Telegram request failed (attempt %d): %s", attempt + 1, e)

        if attempt == 0:
            logger.info("Retrying Telegram send in 60 seconds...")
            time.sleep(60)

    return False
