import logging
import sys


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure logging for GitHub Actions output."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    return logging.getLogger("download_report")
