from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import quote

from app.dashboard.design_tokens import COLORS, RADIUS, SHADOW, SPACING


NAV_ICONS = {
    "Dashboard": "layout",
    "Chat Monitor": "message",
    "Game Monitor": "radar",
    "Feedback Center": "feedback",
    "Member Review": "shield_check",
    "Pending Issues": "task",
    "Event Management": "calendar",
    "Reports": "analytics",
    "FAQ Management": "help_center",
    "VIP Operations": "users",
    "VIP Red Black": "flame",
}

NAV_GROUPS = [
    ("社区运营", ("Dashboard", "Chat Monitor", "Game Monitor", "Feedback Center", "Member Review", "Pending Issues")),
    ("活动增长", ("Event Management", "Reports")),
    ("VIP 工作台", ("VIP Operations", "VIP Red Black")),
    ("系统", ("FAQ Management",)),
]

PAGE_ACTIONS = {
    "Dashboard": ("刷新指标", "查看 Bot"),
    "Chat Monitor": ("风险筛选", "导出记录"),
    "Game Monitor": ("区服对比", "风险巡检"),
    "Feedback Center": ("处理反馈", "批量更新"),
    "Member Review": ("刷新申请", "审核规则"),
    "Pending Issues": ("人工答复", "Bot 回复"),
    "Event Management": ("新建活动", "刷新状态"),
    "Reports": ("生成报告", "下载文档"),
    "FAQ Management": ("导入 FAQ", "更新知识库"),
    "VIP Operations": ("上传 Excel", "刷新快照"),
    "VIP Red Black": ("筛选榜单", "查看明细"),
}

ICONS = {
    "alert": '<circle cx="12" cy="12" r="10"></circle><line x1="12" x2="12" y1="8" y2="12"></line><line x1="12" x2="12.01" y1="16" y2="16"></line>',
    "bar": '<path d="M3 3v18h18"></path><path d="M18 17V9"></path><path d="M13 17V5"></path><path d="M8 17v-3"></path>',
    "calendar": '<rect width="18" height="18" x="3" y="4" rx="2"></rect><path d="M16 2v4"></path><path d="M8 2v4"></path><path d="M3 10h18"></path>',
    "analytics": '<path d="M3 3v18h18"></path><path d="M7 16l3-4 3 2 5-7"></path><path d="M18 7h-4"></path><path d="M18 7v4"></path>',
    "feedback": '<path d="M21 12a8 8 0 0 1-8 8H7l-4 3V6a4 4 0 0 1 4-4h6a8 8 0 0 1 8 10Z"></path><path d="M9 9h6"></path><path d="M9 13h4"></path>',
    "filter": '<path d="M3 6h18"></path><path d="M7 12h10"></path><path d="M10 18h4"></path>',
    "flame": '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 17c1.38 0 2.5-1.12 2.5-2.5 0-.78-.37-1.44-.85-2.05-.63-.8-1.15-1.67-1.15-2.95-1.7 1.18-3 2.73-3 5Z"></path><path d="M12 2C9 5 6 7.5 6 12a6 6 0 0 0 12 0c0-3.2-1.8-5.3-3.6-7.1-.6 1.8-1.5 3-2.4 3.9"></path>',
    "help": '<circle cx="12" cy="12" r="10"></circle><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path><path d="M12 17h.01"></path>',
    "help_center": '<path d="M4 19.5V5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-1.5Z"></path><path d="M9 8a3 3 0 0 1 5.83 1c0 2-3 2.25-3 4"></path><path d="M12 17h.01"></path>',
    "layout": '<rect width="7" height="9" x="3" y="3" rx="1"></rect><rect width="7" height="5" x="14" y="3" rx="1"></rect><rect width="7" height="9" x="14" y="12" rx="1"></rect><rect width="7" height="5" x="3" y="16" rx="1"></rect>',
    "message": '<path d="M21 15a4 4 0 0 1-4 4H7l-4 4V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"></path>',
    "radar": '<circle cx="12" cy="12" r="9"></circle><circle cx="12" cy="12" r="4"></circle><path d="M12 12 18.5 5.5"></path><circle cx="12" cy="12" r="1"></circle>',
    "sparkles": '<path d="m12 3-1.9 5.8L4 11l6.1 2.2L12 19l1.9-5.8L20 11l-6.1-2.2Z"></path><path d="M5 3v4"></path><path d="M3 5h4"></path><path d="M19 17v4"></path><path d="M17 19h4"></path>',
    "task": '<path d="M9 11l2 2 4-5"></path><path d="M20 12v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9"></path><path d="M16 4h4v4"></path>',
    "target": '<circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="6"></circle><circle cx="12" cy="12" r="2"></circle>',
    "shield_check": '<path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3v8Z"></path><path d="m9 12 2 2 4-5"></path>',
    "upload": '<path d="M16 16l-4-4-4 4"></path><path d="M12 12v9"></path><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"></path>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M22 21v-2a4 4 0 0 0-3-3.87"></path>',
    "check": '<path d="M9 11l3 3L22 4"></path><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5"></path><path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"></path>',
    "refresh": '<path d="M21 12a9 9 0 0 1-15.5 6.3"></path><path d="M3 12A9 9 0 0 1 18.5 5.7"></path><path d="M3 19v-5h5"></path><path d="M21 5v5h-5"></path>',
    "globe": '<circle cx="12" cy="12" r="10"></circle><path d="M2 12h20"></path><path d="M12 2a15.3 15.3 0 0 1 0 20"></path><path d="M12 2a15.3 15.3 0 0 0 0 20"></path>',
    "bot": '<path d="M12 8V4H8"></path><rect width="16" height="12" x="4" y="8" rx="3"></rect><path d="M2 14h2"></path><path d="M20 14h2"></path><path d="M9 13v2"></path><path d="M15 13v2"></path>',
}


def icon_svg(name: str) -> str:
    body = ICONS.get(name, ICONS["sparkles"])
    return f'<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">{body}</svg>'


def icon_markdown(name: str, color: str) -> str:
    body = ICONS.get(name, ICONS["sparkles"])
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'width="18" height="18" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )
    return f"![icon](data:image/svg+xml,{quote(svg, safe='')})"


def inject_global_styles(st) -> None:
    # Read the stylesheet on every Streamlit rerun so theme-only iterations stay live.
    theme_path = Path(__file__).with_name("theme.css")
    theme_css = theme_path.read_text(encoding="utf-8")
    token_css = f"""
    :root {{
        --page-bg: {COLORS['background']};
        --surface: {COLORS['card']};
        --surface-muted: {COLORS['surface_muted']};
        --primary: {COLORS['primary']};
        --primary-hover: {COLORS['primary_hover']};
        --primary-soft: {COLORS['primary_soft']};
        --accent: {COLORS['accent']};
        --text-primary: {COLORS['text']};
        --text-secondary: {COLORS['text_secondary']};
        --text-tertiary: {COLORS['text_tertiary']};
        --border: {COLORS['border']};
        --border-strong: {COLORS['border_strong']};
        --success: {COLORS['success']};
        --success-soft: #EDF7F0;
        --warning: {COLORS['warning']};
        --warning-soft: #FFF7E8;
        --danger: {COLORS['danger']};
        --risk-low: {COLORS['risk_low']};
        --danger-soft: #FFF1F0;
        --page-x: {SPACING['page_x']};
        --page-y: {SPACING['page_y']};
        --radius-button: {RADIUS['button']};
        --radius-control: {RADIUS['control']};
        --radius-card: {RADIUS['card']};
        --radius-panel: {RADIUS['panel']};
        --radius-dialog: {RADIUS['dialog']};
        --radius-pill: {RADIUS['pill']};
        --shadow-1: {SHADOW['card']};
        --shadow-2: {SHADOW['hover']};
        --shadow-button: {SHADOW['button']};
        --shadow-3: {SHADOW['overlay']};
        --motion-fast: 140ms;
        --motion-standard: 180ms;
        /* Page reruns should feel immediate; motion is reserved for direct interaction. */
        --motion-enter: 0ms;
        --motion-route: 300ms;
        --ease-standard: cubic-bezier(.2, .8, .2, 1);
        --ease-route: cubic-bezier(.25, .1, .25, 1);
    }}
    """
    st.markdown(f"<style>{token_css}\n{theme_css}</style>", unsafe_allow_html=True)


def render_top_status_bar(
    st,
    *,
    module_label: str,
    db_label: str,
    bot_label: str,
    bot_running: bool,
    tunnel_label: str,
) -> None:
    bot_class = "is-online" if bot_running else "is-warn"
    with st.container(key="global_command_bar", border=False):
        status_col, refresh_col, assistant_col = st.columns([7.2, 1.1, 1.25], vertical_alignment="center")
        with status_col:
            st.markdown(
                f"""
                <div class="workbench-topbar compact-topbar">
                    <div class="topbar-main">
                        <div class="topbar-title">AIDC Workbench / {escape(module_label)}</div>
                    </div>
                    <div class="topbar-chip-row">
                        <span class="topbar-chip topbar-chip-bot {bot_class}" tabindex="0" title="Discord Bot 状态：{escape(bot_label)}">{icon_svg('bot')} Bot {escape(bot_label)}</span>
                        <span class="topbar-chip topbar-chip-database" tabindex="0" title="查看当前数据源更新时间与大小">{icon_svg('database')} {escape(db_label)}</span>
                        <span class="topbar-chip topbar-chip-network" tabindex="0" title="查看公网访问状态">{icon_svg('globe')} {escape(tunnel_label)}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with refresh_col:
            if st.button(
                f"{icon_markdown('refresh', COLORS['primary'])} 刷新",
                key="global_refresh_cache",
                use_container_width=True,
            ):
                st.cache_data.clear()
                st.toast("缓存已刷新")
                st.rerun()
        with assistant_col:
            if st.button(
                f"{icon_markdown('sparkles', COLORS['primary'])} AI 助手",
                key="global_ai_assistant",
                use_container_width=True,
            ):
                st.session_state["show_ai_assistant_panel"] = not st.session_state.get(
                    "show_ai_assistant_panel", False
                )

    if st.session_state.get("show_ai_assistant_panel", False):
        st.markdown(
            f"""
            <div class="ai-assistant-panel">
                <div>
                    <div class="ai-assistant-title">AI 助手入口</div>
                    <div class="ai-assistant-copy">当前页面上下文已准备好，可继续接入摘要、归类、回复和运营建议。</div>
                </div>
                <span class="status-pill success">{icon_svg('check')} 已启用</span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_sidebar_brand(st) -> None:
    st.sidebar.markdown(
        f"""
        <div class="sidebar-logo">
            <div class="logo-mark">{icon_svg('sparkles')}</div>
            <div>
                <div class="logo-title">VIP Operation Center</div>
                <div class="logo-sub">AI Assistant Module</div>
            </div>
        </div>
        <div class="sidebar-status"><span class="sidebar-status-dot"></span> AIDC Workbench Online</div>
        """,
        unsafe_allow_html=True,
    )


def _select_sidebar_page(session_state, page_name: str) -> None:
    """Update navigation state before Streamlit starts the button rerun."""
    session_state["selected_page"] = page_name


def render_sidebar_navigation(
    st,
    page_names,
    page_labels,
    selected_page: str,
    badges: dict[str, int] | None = None,
) -> str:
    badges = badges or {}
    available_pages = set(page_names)
    rendered_pages: set[str] = set()
    for group_label, group_pages in NAV_GROUPS:
        visible_pages = [page for page in group_pages if page in available_pages]
        if not visible_pages:
            continue
        st.sidebar.markdown(f'<div class="nav-label">{escape(group_label)}</div>', unsafe_allow_html=True)
        for page_name in visible_pages:
            rendered_pages.add(page_name)
            badge = badges.get(page_name, 0)
            badge_label = f"  {badge}" if badge else ""
            label = (
                f"{icon_markdown(NAV_ICONS.get(page_name, 'layout'), COLORS['primary'])} "
                f"{page_labels[page_name]}{badge_label}"
            )
            st.sidebar.button(
                label,
                key=f"nav_{page_name}",
                type="primary" if page_name == selected_page else "secondary",
                use_container_width=True,
                on_click=_select_sidebar_page,
                args=(st.session_state, page_name),
            )

    leftovers = [page for page in page_names if page not in rendered_pages]
    if leftovers:
        st.sidebar.markdown('<div class="nav-label">其他</div>', unsafe_allow_html=True)
        for page_name in leftovers:
            badge = badges.get(page_name, 0)
            badge_label = f"  {badge}" if badge else ""
            label = (
                f"{icon_markdown(NAV_ICONS.get(page_name, 'layout'), COLORS['primary'])} "
                f"{page_labels[page_name]}{badge_label}"
            )
            st.sidebar.button(
                label,
                key=f"nav_{page_name}",
                type="primary" if page_name == selected_page else "secondary",
                use_container_width=True,
                on_click=_select_sidebar_page,
                args=(st.session_state, page_name),
            )
    return st.session_state.get("selected_page", selected_page)


def render_sidebar_footer(st, db_path) -> None:
    st.sidebar.markdown(
        f"""
        <div class="nav-label">System</div>
        <div class="sidebar-db">数据库：{escape(str(db_path))}</div>
        <div class="help-card">
            <div class="help-title">AIDC 模块</div>
            Discord 社区运营、AI 回复、反馈归类与活动管理。
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page_header(
    st,
    page_name: str,
    page_label: str,
    page_description: str,
) -> None:
    icon_name = NAV_ICONS.get(page_name, "layout")
    shell_main_html = (
        '<div class="page-shell-main">'
        '<div class="page-kicker">AI Community</div>'
        '<div class="page-title-row">'
        f'<div class="page-icon page-icon-{escape(icon_name)}">{icon_svg(icon_name)}</div>'
        f'<div class="page-heading">{escape(page_label)}</div>'
        "</div>"
        f'<div class="page-description">{escape(page_description)}</div>'
        "</div>"
    )
    if page_name == "Event Management":
        with st.container(key="event_page_header"):
            header_column, action_column = st.columns(
                [1, 0.18],
                vertical_alignment="bottom",
            )
            header_column.markdown(shell_main_html, unsafe_allow_html=True)
            if action_column.button(
                "新建活动",
                key="event_header_create",
                type="primary",
                icon=":material/add:",
                width="stretch",
            ):
                st.session_state["_event_create_dialog_requested"] = True
        return

    actions = PAGE_ACTIONS.get(page_name, ("查看", "刷新"))
    action_html = "".join(
        f'<span class="page-action-chip">{icon_svg("target")} {escape(action)}</span>'
        for action in actions
    )
    st.markdown(
        '<div class="page-shell">'
        + shell_main_html
        + f'<div class="page-action-cluster" aria-label="页面任务">{action_html}</div>'
        + "</div>",
        unsafe_allow_html=True,
    )


def dashboard_card(label: str, value: int | float | str, icon_name: str, note: str = "") -> str:
    safe_label = escape(str(label))
    return (
        f'<div class="dashboard-card" role="group" aria-label="{safe_label}">'
        '<div class="dashboard-top"><div>'
        f'<div class="metric-label">{safe_label}</div>'
        f'<div class="dashboard-number">{escape(str(value))}</div>'
        f'<div class="metric-note">{escape(str(note))}</div>'
        f'</div><div class="icon-box">{icon_svg(icon_name)}</div></div></div>'
    )
