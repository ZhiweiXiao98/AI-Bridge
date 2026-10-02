"""侧栏独立提示框和图标入口的离线 DOM 回归，不访问真实站点。"""

from bs4 import BeautifulSoup
import pytest
from selenium.webdriver.common.by import By

from app.core.browser_fixture import BrowserFixture
from app.core.driver.interaction import InteractionManager


class DOMElement:
    def __init__(self, driver, tag):
        self.driver, self.tag = driver, tag

    def is_displayed(self):
        return not any(node.has_attr("hidden") or "display:none" in node.get("style", "").replace(" ", "")
                       for node in [self.tag, *self.tag.parents] if getattr(node, "attrs", None) is not None)

    def is_enabled(self):
        return not self.tag.has_attr("disabled")

    def get_attribute(self, name):
        return str(self.tag) if name == "outerHTML" else self.tag.get(name)

    def find_elements(self, by, selector):
        assert by == By.CSS_SELECTOR
        return [DOMElement(self.driver, tag) for tag in self.tag.select(selector)]

    def click(self):
        self.driver.clicked.append(self.tag.get("id"))
        self.driver.current_url = "http://127.0.0.1/chat#new"


class DOMDriver:
    def __init__(self, html):
        self.soup = BeautifulSoup(html, "html.parser")
        self.current_url = "http://127.0.0.1/chat#old"
        self.clicked = []
        self.queries = []

    def find_elements(self, by, selector):
        self.queries.append((by, selector))
        if by == By.CSS_SELECTOR:
            tags = self.soup.select(selector)
        else:
            assert by == By.XPATH
            assert "@data-action='new-chat'" in selector
            labels = {"新建对话", "新建聊天", "创建新对话"}
            tags = [button for button in self.soup.select("button")
                    if button.get("data-action") == "new-chat"
                    or button.get("aria-label") in labels
                    or " ".join(button.get_text().split()) in labels]
        return [DOMElement(self, tag) for tag in tags]


def test_icon_only_fixture_with_external_tooltip_creates_one_chat():
    driver = DOMDriver(BrowserFixture().html)
    button = driver.soup.select_one("#new-chat")
    assert not button.get_text(strip=True) and not button.get("aria-label") and not button.get("data-action")
    assert driver.soup.select_one('[role="tooltip"]').get_text() == "创建新对话"
    assert InteractionManager(driver).new_chat() == (True, "已新建网页会话")
    assert driver.clicked == ["new-chat"]


def test_existing_labeled_button_takes_priority_without_double_trigger():
    driver = DOMDriver(BrowserFixture().html)
    labeled = driver.soup.new_tag("button", id="text-create")
    labeled.string = "创建新对话"
    driver.soup.aside.append(labeled)
    assert InteractionManager(driver).new_chat()[0]
    assert driver.clicked == ["text-create"]
    assert (By.CSS_SELECTOR, "button.aa-sidebar-toolbar__btn") not in driver.queries


@pytest.mark.parametrize("html", [
    '<button id="upload"><i class="fa fa-plus"></i></button>',
    '<button id="delete" class="aa-sidebar-toolbar__btn"><i class="fa fa-trash"></i></button>',
    '<button class="aa-sidebar-toolbar__btn-other"><i class="fa fa-plus"></i></button>',
    '<button class="aa-sidebar-toolbar__btn" hidden><i class="fa fa-plus"></i></button>',
    '<button class="aa-sidebar-toolbar__btn" disabled><i class="fa fa-plus"></i></button>',
    '<button class="aa-sidebar-toolbar__btn" aria-disabled="true"><i class="fa fa-plus"></i></button>',
    '<button class="aa-sidebar-toolbar__btn"><i class="fa fa-plus" hidden></i></button>',
    '<button class="aa-sidebar-toolbar__btn"><i class="fa fa-plus"></i></button>' * 2,
])
def test_unrelated_hidden_disabled_or_ambiguous_controls_are_never_clicked(html):
    driver = DOMDriver(html)
    ok, message = InteractionManager(driver).new_chat()
    assert not ok and "唯一" in message
    assert driver.clicked == []


def test_ambiguous_labeled_buttons_do_not_fall_back_to_sidebar():
    driver = DOMDriver(BrowserFixture().html)
    for label in ("创建新对话", "新建聊天"):
        button = driver.soup.new_tag("button")
        button.string = label
        driver.soup.aside.append(button)
    assert not InteractionManager(driver).new_chat()[0]
    assert driver.clicked == []
    assert (By.CSS_SELECTOR, "button.aa-sidebar-toolbar__btn") not in driver.queries
