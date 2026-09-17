from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from app.dashboard.auth import require_dashboard_auth
from app.dashboard.bot_control_service import BotControlService
from app.dashboard.cache_utils import file_fingerprint
from app.dashboard.styles import (
    inject_global_styles,
    render_page_header,
    render_sidebar_brand,
    render_sidebar_footer,
    render_sidebar_navigation,
    render_top_status_bar,
)
from app.dashboard.views import (
    chat_monitor,
    dashboard,
    event_management,
    faq_management,
    feedback_center,
    game_monitor,
    member_review,
    pending_issues,
    reports,
    vip_operations,
    vip_red_black,
)
from app.database.migrations.init_db import init_database
from app.database.repositories.pending_ticket_repository import PendingTicketRepository
from config.settings import BASE_DIR, get_settings


def _init_database_once(st, db_path) -> None:
    @st.cache_resource(show_spinner=False)
    def _cached_init_database(path: str) -> str:
        return str(init_database(path))

    _cached_init_database(str(db_path))


def _database_label(db_path: Path) -> str:
    try:
        stat = db_path.stat()
    except FileNotFoundError:
        return "数据源：尚未创建"
    updated_at = datetime.fromtimestamp(stat.st_mtime).strftime("%m/%d %H:%M")
    size_mb = stat.st_size / (1024 * 1024)
    return f"数据源：{updated_at} 更新 · {size_mb:.1f} MB"


def _latest_tunnel_label() -> str:
    log_path = BASE_DIR / "logs" / "public-tunnel.out.log"
    if not log_path.exists():
        return "公网：本地模式"
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "公网：状态未知"
    matches = re.findall(r"https://[^\s\"']+", text)
    if not matches:
        return "公网：本地模式"
    return "公网访问"


def _latest_tunnel_label_cached(st) -> str:
    @st.cache_data(ttl=15, show_spinner=False)
    def _load(_fingerprint: tuple[int, int]) -> str:
        return _latest_tunnel_label()

    return _load(file_fingerprint(BASE_DIR / "logs" / "public-tunnel.out.log"))


def _navigation_badges(st, db_path: Path) -> dict[str, int]:
    @st.cache_data(ttl=10, show_spinner=False)
    def _load(path: str) -> dict[str, int]:
        try:
            pending_count = PendingTicketRepository(Path(path)).count_open()
        except Exception:
            pending_count = 0
        return {"Pending Issues": pending_count} if pending_count else {}

    # The Discord bot updates the SQLite file for every collected message.
    # Using the whole-file mtime here invalidated navigation caches constantly.
    return _load(str(db_path))


def _bot_status_cached(st, settings):
    @st.cache_data(ttl=3, show_spinner=False)
    def _load(_pid_fingerprint: tuple[int, int], _lock_fingerprint: tuple[int, int]):
        return BotControlService(settings).status()

    data_dir = Path(settings.db_path).parent
    return _load(
        file_fingerprint(data_dir / "discord_bot.pid"),
        file_fingerprint(data_dir / "discord_bot.lock"),
    )


PAGE_PATHS = {
    "/": "Dashboard",
    "/dashboard": "Dashboard",
    "/chat_monitor": "Chat Monitor",
    "/game_monitor": "Game Monitor",
    "/feedback_center": "Feedback Center",
    "/member_review": "Member Review",
    "/pending_issues": "Pending Issues",
    "/event_management": "Event Management",
    "/vip_operations": "VIP Operations",
    "/vip_red_black": "VIP Red Black",
    "/reports": "Reports",
    "/faq_management": "FAQ Management",
}

PAGE_LABELS = {
    "Dashboard": "数据总览",
    "Chat Monitor": "聊天监控",
    "Game Monitor": "游戏内监控",
    "Feedback Center": "反馈中心",
    "Member Review": "成员审核",
    "Pending Issues": "FAQ 待答",
    "Event Management": "活动管理",
    "VIP Operations": "VIP 运营",
    "VIP Red Black": "红黑榜",
    "Reports": "运营报告",
    "FAQ Management": "FAQ 管理",
}

PAGE_DESCRIPTIONS = {
    "Dashboard": "查看今日 Discord 社区核心指标、Bot 在线状态和基础运营趋势。",
    "Chat Monitor": "聚焦已监听聊天频道中的风险发言，用日历和表格辅助快速巡检。",
    "Game Monitor": "查看当前有效角色的游戏内消息趋势与风险言论，不含处理工作流。",
    "Feedback Center": "集中处理玩家意见、BUG 与建议，并跟踪反馈状态和解决进展。",
    "Member Review": "自动识别 Discord 加入申请中的游戏角色信息，并根据审核规则生成审核建议。",
    "Pending Issues": "集中处理 FAQ 未命中的玩家私信，支持状态更新和 Bot 私信回复。",
    "Event Management": "创建、排期、发布 Discord 活动，并查看投票参与与活动效果。",
    "VIP Operations": "同步 AE 项目 24 的 VIP 数据，查看玩家价值、风险和触达优先级。",
    "VIP Red Black": "基于近 7 日充值变化识别红榜玩家与高价值消费偏弱玩家。",
    "Reports": "生成和下载社区运营日报、周报与自定义报告。",
    "FAQ Management": "导入 FAQ 数据并管理 AI 助手可用知识条目。",
}

PAGES = {
    "Dashboard": dashboard.render,
    "Chat Monitor": chat_monitor.render,
    "Game Monitor": game_monitor.render,
    "Feedback Center": feedback_center.render,
    "Member Review": member_review.render,
    "Pending Issues": pending_issues.render,
    "Event Management": event_management.render,
    "VIP Operations": vip_operations.render,
    "VIP Red Black": vip_red_black.render,
    "Reports": reports.render,
    "FAQ Management": faq_management.render,
}


def page_from_url(url: str | None) -> str:
    if not url:
        return "Dashboard"

    from urllib.parse import urlparse

    path = urlparse(url).path.rstrip("/") or "/"
    return PAGE_PATHS.get(path, "Dashboard")


def get_selected_page(session_state, default_page: str, page_names: tuple[str, ...]) -> str:
    if session_state.get("selected_page") not in page_names:
        session_state.selected_page = default_page
    return session_state.selected_page


def page_transition_key(page_name: str) -> str:
    """Return a stable Streamlit key that changes only when the active module changes."""
    slug = re.sub(r"[^a-z0-9]+", "_", page_name.lower()).strip("_")
    return f"page_transition_{slug or 'dashboard'}"


def main() -> None:
    import streamlit as st

    settings = get_settings()
    _init_database_once(st, settings.db_path)

    st.set_page_config(
        page_title="VIP Operation Center · AIDC",
        layout="wide",
        initial_sidebar_state="auto",
    )
    inject_global_styles(st)

    if not require_dashboard_auth(st, settings.dashboard_password):
        return

    render_sidebar_brand(st)
    page_names = tuple(PAGES.keys())
    default_page = page_from_url(getattr(st.context, "url", None))
    selected_page = get_selected_page(st.session_state, default_page, page_names)
    selected_page = render_sidebar_navigation(
        st,
        page_names=page_names,
        page_labels=PAGE_LABELS,
        selected_page=selected_page,
        badges=_navigation_badges(st, Path(settings.db_path)),
    )
    render_sidebar_footer(st, settings.db_path)

    with st.container(key=page_transition_key(selected_page)):
        bot_status = _bot_status_cached(st, settings)
        render_top_status_bar(
            st,
            module_label=PAGE_LABELS[selected_page],
            db_label=_database_label(Path(settings.db_path)),
            bot_label=bot_status.label,
            bot_running=bot_status.is_running,
            tunnel_label=_latest_tunnel_label_cached(st),
        )
        render_page_header(
            st,
            page_name=selected_page,
            page_label=PAGE_LABELS[selected_page],
            page_description=PAGE_DESCRIPTIONS[selected_page],
        )
        PAGES[selected_page](st, settings.db_path)


if __name__ == "__main__":
    main()
