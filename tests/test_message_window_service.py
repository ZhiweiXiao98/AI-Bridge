from app.ui.pages.chat.services.message_window_service import MessageWindowService


def test_message_window_service_uses_large_window_but_still_supports_load_more():
    service = MessageWindowService(default_turns=1, step_turns=1)
    messages = [{"id": str(i)} for i in range(6)]

    visible, has_more = service.slice_messages("api", messages)

    assert visible == messages[-2:]
    assert has_more is True

    service.expand_for_mode("api")
    visible, has_more = service.slice_messages("api", messages)

    assert visible == messages[-4:]
    assert has_more is True


def test_message_window_service_default_window_is_large():
    service = MessageWindowService()
    messages = [{"id": str(i)} for i in range(400)]

    visible, has_more = service.slice_messages("browser", messages)

    assert visible == messages
    assert has_more is False
