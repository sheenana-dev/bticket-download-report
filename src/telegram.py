import logging
import os
import time
from typing import Optional

import requests

from src.config import TelegramConfig

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_DOCUMENT_URL = "https://api.telegram.org/bot{token}/sendDocument"


def send_telegram_message(config: TelegramConfig, message: str, chat_id: Optional[str] = None) -> bool:
    """Send a message to the configured Telegram chat. Retries once after 60s on failure.

    ``chat_id`` overrides the configured destination (used by the revenue
    report, which may go to a different group than the download report).
    """
    url = TELEGRAM_API_URL.format(token=config.bot_token)
    payload = {
        "chat_id": chat_id or config.chat_id,
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


def send_telegram_document(
    config: TelegramConfig,
    file_path: str,
    caption: str = "",
    chat_id: Optional[str] = None,
) -> bool:
    """Upload a file (e.g. the monthly revenue PDF) to Telegram. Retries once after 60s.

    Caption is HTML and capped by Telegram at 1024 characters.
    """
    url = TELEGRAM_DOCUMENT_URL.format(token=config.bot_token)
    data = {
        "chat_id": chat_id or config.chat_id,
        "caption": caption[:1024],
        "parse_mode": "HTML",
    }

    for attempt in range(2):
        try:
            with open(file_path, "rb") as fh:
                files = {"document": (os.path.basename(file_path), fh, "application/pdf")}
                resp = requests.post(url, data=data, files=files, timeout=60)
            body = resp.json()
            if resp.ok and body.get("ok"):
                logger.info("Telegram document sent successfully: %s", file_path)
                return True
            logger.error(
                "Telegram sendDocument error (attempt %d): %s",
                attempt + 1, body.get("description", resp.text),
            )
        except (requests.RequestException, OSError, ValueError) as e:
            logger.error("Telegram sendDocument failed (attempt %d): %s", attempt + 1, e)

        if attempt == 0:
            logger.info("Retrying Telegram document send in 60 seconds...")
            time.sleep(60)

    return False
