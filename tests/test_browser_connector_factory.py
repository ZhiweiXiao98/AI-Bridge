from app.core.driver import ChromeConnector
from app.core.driver.embedded_qt_connector import EmbeddedQtBrowserConnector
from app.core.driver.factory import (
    EMBEDDED_QT_SOURCE,
    EXTERNAL_CHROME_SOURCE,
    create_browser_connector,
    normalize_browser_source,
)


def test_normalize_browser_source_keeps_external_chrome_default():
    assert normalize_browser_source("") == EXTERNAL_CHROME_SOURCE
    assert normalize_browser_source("chrome") == EXTERNAL_CHROME_SOURCE
    assert normalize_browser_source("external_chrome") == EXTERNAL_CHROME_SOURCE


def test_normalize_browser_source_accepts_embedded_aliases():
    assert normalize_browser_source("embedded") == EMBEDDED_QT_SOURCE
    assert normalize_browser_source("webengine") == EMBEDDED_QT_SOURCE
    assert normalize_browser_source("embedded_qt") == EMBEDDED_QT_SOURCE


def test_create_browser_connector_preserves_external_chrome():
    connector = create_browser_connector({"browser_source": "external_chrome", "chrome_port": 9527})

    assert isinstance(connector, ChromeConnector)


def test_embedded_qt_connector_reports_unattached_executor():
    connector = create_browser_connector({"browser_source": "embedded_qt"})

    assert isinstance(connector, EmbeddedQtBrowserConnector)
    ok, info = connector.connect()
    assert ok is False
    assert info["error_code"] == "embedded_browser_executor_not_attached"

