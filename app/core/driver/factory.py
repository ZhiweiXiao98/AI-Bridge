# filename: app/core/driver/factory.py
from __future__ import annotations

from typing import Any

from app.core.app_constants import CHROME_PORT
from app.core.logging import get_logger

from . import ChromeConnector

logger = get_logger("app.core.driver.factory", side="worker")


EXTERNAL_CHROME_SOURCE = "external_chrome"
EMBEDDED_QT_SOURCE = "embedded_qt"
DEFAULT_BROWSER_SOURCE = EXTERNAL_CHROME_SOURCE


def normalize_browser_source(value: Any) -> str:
    source = str(value or DEFAULT_BROWSER_SOURCE).strip().lower()
    aliases = {
        "chrome": EXTERNAL_CHROME_SOURCE,
        "external": EXTERNAL_CHROME_SOURCE,
        "external_chrome": EXTERNAL_CHROME_SOURCE,
        "qt": EMBEDDED_QT_SOURCE,
        "webengine": EMBEDDED_QT_SOURCE,
        "embedded": EMBEDDED_QT_SOURCE,
        "embedded_qt": EMBEDDED_QT_SOURCE,
    }
    return aliases.get(source, DEFAULT_BROWSER_SOURCE)


def create_browser_connector(config: dict[str, Any] | None = None):
    """Create the active browser connector without changing Chrome defaults."""
    config = config if isinstance(config, dict) else {}
    source = normalize_browser_source(config.get("browser_source"))
    if source == EMBEDDED_QT_SOURCE:
        from .embedded_qt_connector import EmbeddedQtBrowserConnector

        logger.info("[BrowserSource] using embedded Qt browser connector")
        return EmbeddedQtBrowserConnector(config=config)

    port = int(config.get("chrome_port", CHROME_PORT) or CHROME_PORT)
    logger.info("[BrowserSource] using external Chrome connector | port=%s", port)
    return ChromeConnector(port=port, config=config)
