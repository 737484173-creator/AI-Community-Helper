from app.dashboard.streamlit_app import get_selected_page, page_from_url, page_transition_key


class SessionState(dict):
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


def test_page_from_url_defaults_to_dashboard() -> None:
    assert page_from_url(None) == "Dashboard"
    assert page_from_url("http://localhost:8502/") == "Dashboard"


def test_page_from_url_maps_dashboard_pages() -> None:
    assert page_from_url("http://localhost:8502/faq_management") == "FAQ Management"
    assert page_from_url("http://localhost:8502/reports") == "Reports"
    assert page_from_url("http://localhost:8502/chat_monitor") == "Chat Monitor"
    assert page_from_url("http://localhost:8502/game_monitor") == "Game Monitor"
    assert page_from_url("http://localhost:8502/vip_operations") == "VIP Operations"
    assert page_from_url("http://localhost:8502/vip_red_black") == "VIP Red Black"


def test_page_from_url_ignores_query_string() -> None:
    assert page_from_url("http://localhost:8502/event_management?x=1") == "Event Management"


def test_get_selected_page_keeps_existing_valid_page() -> None:
    state = SessionState(selected_page="Feedback Center")

    selected = get_selected_page(
        state,
        default_page="Chat Monitor",
        page_names=("Dashboard", "Chat Monitor", "Feedback Center"),
    )

    assert selected == "Feedback Center"


def test_get_selected_page_uses_default_when_missing_or_invalid() -> None:
    state = SessionState()

    selected = get_selected_page(
        state,
        default_page="Chat Monitor",
        page_names=("Dashboard", "Chat Monitor", "Feedback Center"),
    )

    assert selected == "Chat Monitor"
    assert state.selected_page == "Chat Monitor"


def test_page_transition_key_is_stable_and_css_safe() -> None:
    assert page_transition_key("Chat Monitor") == "page_transition_chat_monitor"
    assert page_transition_key("FAQ 管理") == "page_transition_faq"
