from __future__ import annotations

from app.dashboard.styles import NAV_GROUPS, _select_sidebar_page, render_sidebar_navigation


class SidebarCapture:
    def __init__(self) -> None:
        self.buttons: list[dict] = []

    def markdown(self, *_args, **_kwargs) -> None:
        return None

    def button(self, label: str, **kwargs) -> bool:
        self.buttons.append({"label": label, **kwargs})
        return True


class StreamlitCapture:
    def __init__(self) -> None:
        self.session_state = {"selected_page": "Dashboard"}
        self.sidebar = SidebarCapture()


def test_select_sidebar_page_updates_session_state() -> None:
    state = {"selected_page": "Dashboard"}

    _select_sidebar_page(state, "Chat Monitor")

    assert state["selected_page"] == "Chat Monitor"


def test_sidebar_navigation_uses_callbacks_without_forcing_an_extra_rerun() -> None:
    st = StreamlitCapture()

    selected = render_sidebar_navigation(
        st,
        page_names=("Dashboard", "Chat Monitor"),
        page_labels={"Dashboard": "数据总览", "Chat Monitor": "聊天监控"},
        selected_page="Dashboard",
    )

    assert selected == "Dashboard"
    assert len(st.sidebar.buttons) == 2
    for button in st.sidebar.buttons:
        assert button["on_click"] is _select_sidebar_page
        assert button["args"][0] is st.session_state


def test_game_monitor_is_adjacent_to_chat_monitor_in_community_group() -> None:
    community_pages = dict(NAV_GROUPS)["社区运营"]

    chat_index = community_pages.index("Chat Monitor")
    assert community_pages[chat_index + 1] == "Game Monitor"
