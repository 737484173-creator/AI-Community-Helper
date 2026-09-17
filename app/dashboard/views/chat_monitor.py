from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from html import escape
import math
import re

import altair as alt
import pandas as pd

from app.bot.content_moderation import (
    analyze_public_message,
    normalize_monitored_channel_name,
    public_message_risk_level,
    public_message_risk_type,
)
from app.dashboard.design_tokens import COLORS
from app.dashboard.discord_identity_service import DiscordIdentityService
from app.dashboard.export_utils import records_to_csv
from app.dashboard.formatters import date_range_to_datetimes, rows_to_records
from app.dashboard.member_moderation_service import (
    ACTION_BAN,
    ACTION_KICK,
    ACTION_LABELS,
    ACTION_TIMEOUT,
    TIMEOUT_OPTIONS,
    MemberModerationService,
)
from app.dashboard.styles import icon_svg
from app.database.repositories.message_repository import MessageRepository


MONITORED_CHANNELS = (
    "game-chat",
    "ask_for_help",
    "suggestion-discussion",
)
CHANNEL_OPTIONS = ("全部", *MONITORED_CHANNELS)
MONITORED_CHANNELS_LABEL = "、".join(f"#{channel}" for channel in MONITORED_CHANNELS)
RISK_LEVELS = ("全部", "高风险", "中风险", "低风险")
RISK_TYPES = ("全部", "脏字/攻击", "强烈负面", "高强度情绪", "风险表达")
STATUS_OPTIONS = ("全部", "待处理", "已处理", "已忽略")
DISCORD_MENTION_PATTERN = re.compile(r"<@!?(\d+)>")


def _cached_channel_messages(st, db_path, start_time, end_time, limit: int) -> list[dict]:
    @st.cache_data(ttl=20, show_spinner=False)
    def _load(path: str, start_value, end_value, row_limit: int) -> list[dict]:
        rows = MessageRepository(path).list_channels_messages_between(
            start_time=start_value,
            end_time=end_value,
            channel_names=MONITORED_CHANNELS,
            limit=row_limit,
        )
        return rows_to_records(rows)

    return _load(str(db_path), start_time, end_time, limit)


def _month_bounds(target_date: date) -> tuple[date, date]:
    last_day = calendar.monthrange(target_date.year, target_date.month)[1]
    return date(target_date.year, target_date.month, 1), date(target_date.year, target_date.month, last_day)


def _shift_month(target_date: date, offset: int) -> date:
    month_index = target_date.year * 12 + target_date.month - 1 + offset
    year, zero_based_month = divmod(month_index, 12)
    return date(year, zero_based_month + 1, 1)


def _parse_created_time(value: object) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _compact_datetime(value: object) -> str:
    parsed = _parse_created_time(value)
    if not parsed:
        return str(value or "-")
    return parsed.strftime("%Y/%m/%d %H:%M")


def _short_text(value: object, limit: int = 72) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _discord_mention_ids(message: object) -> tuple[str, ...]:
    return tuple(dict.fromkeys(DISCORD_MENTION_PATTERN.findall(str(message or ""))))


def _replace_discord_mentions(message: object, names_by_id: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return f"@{names_by_id.get(match.group(1), '未知用户')}"

    return DISCORD_MENTION_PATTERN.sub(replace, str(message or ""))


def _resolved_record_identities(st, db_path, record: dict) -> dict[str, str]:
    author_id = str(record.get("discord_user_id") or "").strip()
    user_ids = tuple(dict.fromkeys((author_id, *_discord_mention_ids(record.get("message")))))
    guild_id = str(record.get("guild_id") or "").strip() or None
    session_cache = st.session_state.setdefault("chat_discord_identity_cache", {})
    names_by_id: dict[str, str] = {}
    stored_author_name = str(record.get("discord_user_name") or "").strip()
    if author_id and stored_author_name:
        names_by_id[author_id] = stored_author_name
        session_cache[f"{guild_id or '-'}:{author_id}"] = stored_author_name

    resolver = DiscordIdentityService(db_path)
    for user_id in user_ids:
        if not user_id or user_id in names_by_id:
            continue
        cache_key = f"{guild_id or '-'}:{user_id}"
        if cache_key not in session_cache:
            try:
                session_cache[cache_key] = resolver.resolve_display_name(user_id, guild_id) or ""
            except RuntimeError:
                session_cache[cache_key] = ""
        cached_name = str(session_cache.get(cache_key) or "").strip()
        if cached_name:
            names_by_id[user_id] = cached_name
    return names_by_id


def _risk_type(reason: str | None) -> str:
    return public_message_risk_type(reason)


def _confidence_for_level(level: str) -> float:
    return {"高风险": 0.92, "中风险": 0.78, "低风险": 0.64}.get(level, 0.6)


def _risk_status(record_id: object) -> str:
    return str(__import__("streamlit").session_state.get(f"chat_risk_status_{record_id}", "待处理"))


def _set_risk_status(record_id: object, status: str) -> None:
    __import__("streamlit").session_state[f"chat_risk_status_{record_id}"] = status


def _reset_chat_filters() -> None:
    st_state = __import__("streamlit").session_state
    today = date.today()
    st_state["chat_date_quick_range"] = "今天"
    st_state["chat_start_date"] = today
    st_state["chat_end_date"] = today


def _dedupe_nearby_duplicates(records: list[dict], window_seconds: int = 5) -> list[dict]:
    deduped: list[dict] = []
    seen_times: dict[tuple[object, ...], list[datetime]] = {}

    for record in records:
        key = (
            record.get("discord_user_id"),
            record.get("channel_id"),
            record.get("message"),
        )
        created_time = _parse_created_time(record.get("created_time"))
        if created_time is None:
            deduped.append(record)
            continue

        nearby_times = seen_times.setdefault(key, [])
        if any(abs((known_time - created_time).total_seconds()) <= window_seconds for known_time in nearby_times):
            continue

        nearby_times.append(created_time)
        deduped.append(record)

    return deduped


def _risk_records(records: list[dict]) -> list[dict]:
    output = []
    for record in records:
        message = str(record.get("message") or "")
        analysis = analyze_public_message(message)
        if not analysis.should_capture:
            continue

        reason = analysis.reason or "风险表达"
        level = public_message_risk_level(message, reason) or "低风险"
        record_id = record.get("id")
        output.append(
            {
                "id": record_id,
                "discord_user_id": record.get("discord_user_id"),
                "discord_user_name": record.get("discord_user_name"),
                "channel_id": record.get("channel_id"),
                "guild_id": record.get("guild_id"),
                "channel_name": (
                    normalize_monitored_channel_name(record.get("channel_name"))
                    or MONITORED_CHANNELS[0]
                ),
                "message": message,
                "created_time": record.get("created_time"),
                "discord_message_id": record.get("discord_message_id"),
                "risk_reason": reason,
                "risk_type": _risk_type(reason),
                "risk_level": level,
                "confidence": _confidence_for_level(level),
                "status": _risk_status(record_id),
            }
        )
    return output


def _risk_counts_for_records(records: list[dict], status: str | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        if status and record.get("status") != status:
            continue
        created_time = _parse_created_time(record.get("created_time"))
        if not created_time:
            continue
        risk_date = created_time.date().isoformat()
        counts[risk_date] = counts.get(risk_date, 0) + 1
    return counts


def _build_risk_calendar_html(
    target_month: date,
    today: date,
    risk_counts: dict[str, int],
    badge_label: str = "未处理",
) -> str:
    month_start, _ = _month_bounds(target_month)
    first_weekday, month_days = calendar.monthrange(month_start.year, month_start.month)
    cells: list[date | None] = [None] * first_weekday
    cells.extend(date(month_start.year, month_start.month, day) for day in range(1, month_days + 1))
    while len(cells) % 7:
        cells.append(None)

    weekday_cells = "".join(f"<div class='chat-calendar-weekday'>{label}</div>" for label in ("一", "二", "三", "四", "五", "六", "日"))
    day_cells = []
    for cell_date in cells:
        if cell_date is None:
            day_cells.append("<div class='chat-calendar-day empty'></div>")
            continue

        count = risk_counts.get(cell_date.isoformat(), 0)
        today_class = " today" if cell_date == today else ""
        risk_badge = (
            f"<span class='chat-calendar-risk' title='{badge_label} {count} 条'>{count}</span>"
            if count
            else ""
        )
        day_cells.append(
            f"<div class='chat-calendar-day{today_class}'>"
            f"<span>{cell_date.day}</span>"
            f"{risk_badge}"
            "</div>"
        )

    return f"""
    <div class="chat-calendar">
        {weekday_cells}
        {''.join(day_cells)}
    </div>
    """


def _close_calendar_dialog(st_state) -> None:
    st_state["chat_calendar_open"] = False


def _render_calendar_dialog(st, db_path) -> None:
    def dismiss_calendar_dialog() -> None:
        _close_calendar_dialog(st.session_state)

    @st.dialog(
        "日历视图",
        width="large",
        on_dismiss=dismiss_calendar_dialog,
    )
    def calendar_dialog() -> None:
        today = date.today()
        current_month = st.session_state.get("chat_calendar_month", today.replace(day=1))
        if not isinstance(current_month, date):
            current_month = today.replace(day=1)
        current_month = current_month.replace(day=1)
        month_start, month_end = _month_bounds(current_month)
        status_end = min(month_end, today)

        previous_month = _shift_month(current_month, -1)
        next_month = _shift_month(current_month, 1)
        previous_col, title_col, next_col, today_col = st.columns([1, 2.2, 1, 1.2])
        if previous_col.button("← 上月", use_container_width=True, key="chat_calendar_previous"):
            st.session_state["chat_calendar_month"] = previous_month
            st.rerun()
        title_col.markdown(
            f"<div class='chat-calendar-title'>{current_month.year} 年 {current_month.month} 月</div>",
            unsafe_allow_html=True,
        )
        if next_col.button(
            "下月 →",
            use_container_width=True,
            key="chat_calendar_next",
            disabled=next_month > today.replace(day=1),
        ):
            st.session_state["chat_calendar_month"] = next_month
            st.rerun()
        if today_col.button("回到本月", use_container_width=True, key="chat_calendar_today"):
            st.session_state["chat_calendar_month"] = today.replace(day=1)
            st.rerun()

        scope = st.segmented_control(
            "显示范围",
            options=("仅未处理", "全部风险"),
            default="仅未处理",
            key="chat_calendar_scope",
        )
        if status_end < month_start:
            risk_records: list[dict] = []
        else:
            start_time, end_time = date_range_to_datetimes(month_start, status_end)
            rows = _cached_channel_messages(st, db_path, start_time, end_time, 10000)
            risk_records = _risk_records(rows)
        pending_only = scope == "仅未处理"
        risk_counts = _risk_counts_for_records(
            risk_records,
            status="待处理" if pending_only else None,
        )
        visible_total = sum(risk_counts.values())
        st.caption(
            f"当前显示 {visible_total} 条{'未处理' if pending_only else '风险'}记录。蓝色描边表示今天，数字表示当天记录数。"
        )
        st.markdown(
            _build_risk_calendar_html(
                current_month,
                today,
                risk_counts,
                badge_label="未处理" if pending_only else "风险",
            ),
            unsafe_allow_html=True,
        )

        available_dates = sorted(
            (date.fromisoformat(value) for value, count in risk_counts.items() if count > 0),
            reverse=True,
        )
        select_col, open_col = st.columns([3, 1])
        selected_date = select_col.selectbox(
            "选择有记录的日期",
            options=available_dates,
            format_func=lambda value: (
                f"{value.strftime('%Y/%m/%d')} · {risk_counts.get(value.isoformat(), 0)} 条"
            ),
            placeholder="本月暂无符合条件的日期",
            disabled=not available_dates,
            key=f"chat_calendar_date_{current_month:%Y_%m}_{'pending' if pending_only else 'all'}",
        )
        if open_col.button(
            "查看当天记录",
            use_container_width=True,
            disabled=selected_date is None,
            key="chat_calendar_open_date",
        ):
            st.session_state["chat_date_quick_range"] = "自定义"
            st.session_state["chat_start_date"] = selected_date
            st.session_state["chat_end_date"] = selected_date
            _close_calendar_dialog(st.session_state)
            st.rerun()

        if st.button("关闭", use_container_width=True, key="chat_calendar_close"):
            _close_calendar_dialog(st.session_state)
            st.rerun()

    calendar_dialog()


def _render_chat_monitor_css(st) -> None:
    st.markdown(
        """
        <style>
        .chat-risk-pulse {
            display: grid;
            grid-template-columns: minmax(250px, .72fr) minmax(0, 1.6fr);
            min-height: 164px;
            margin: 10px 0 20px;
            overflow: hidden;
            border: 1px solid var(--border);
            border-radius: var(--radius-panel);
            background: var(--surface);
            box-shadow: var(--shadow-1);
            animation: chat-workspace-enter var(--motion-enter) var(--ease-standard) both;
            transition:
                transform var(--motion-standard) var(--ease-standard),
                border-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        .chat-risk-pulse:hover {
            transform: translateY(-2px);
            border-color: color-mix(in srgb, var(--primary) 20%, var(--border));
            box-shadow: var(--shadow-2);
        }
        .chat-risk-primary {
            position: relative;
            display: flex;
            padding: 22px 24px;
            flex-direction: column;
            justify-content: space-between;
            border-right: 1px solid var(--border);
            background: color-mix(in srgb, var(--primary-soft) 24%, var(--surface));
            transition:
                background-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        .chat-risk-primary:hover {
            background: color-mix(in srgb, var(--primary-soft) 50%, var(--surface));
            box-shadow: inset -1px 0 0 color-mix(in srgb, var(--primary) 12%, transparent);
        }
        .chat-risk-primary.warning {
            background: color-mix(in srgb, var(--warning-soft) 42%, var(--surface));
        }
        .chat-risk-primary.danger {
            background: color-mix(in srgb, var(--danger-soft) 42%, var(--surface));
        }
        .chat-risk-primary.warning:hover {
            background: color-mix(in srgb, var(--warning-soft) 64%, var(--surface));
        }
        .chat-risk-primary.danger:hover {
            background: color-mix(in srgb, var(--danger-soft) 64%, var(--surface));
        }
        .chat-risk-primary::after {
            position: absolute;
            right: 0;
            bottom: 0;
            width: 48%;
            height: 2px;
            background: var(--primary);
            content: "";
            opacity: .72;
            transition:
                width var(--motion-standard) var(--ease-standard),
                opacity var(--motion-fast) var(--ease-standard);
        }
        .chat-risk-primary:hover::after {
            width: 72%;
            opacity: 1;
        }
        .chat-risk-primary.warning::after { background: var(--warning); }
        .chat-risk-primary.danger::after { background: var(--danger); }
        .chat-risk-primary-label,
        .chat-risk-context-label {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: var(--text-secondary);
            font-size: 12px;
            font-weight: 680;
        }
        .chat-risk-primary-label svg,
        .chat-risk-context-label svg {
            width: 16px;
            height: 16px;
            color: var(--primary);
            transition:
                transform var(--motion-standard) var(--ease-standard),
                filter var(--motion-standard) var(--ease-standard);
        }
        .chat-risk-primary:hover .chat-risk-primary-label svg,
        .chat-risk-context:hover .chat-risk-context-label svg {
            transform: translateY(-1px) scale(1.06);
            filter: drop-shadow(0 3px 5px color-mix(in srgb, var(--primary) 24%, transparent));
        }
        .chat-risk-primary.warning .chat-risk-primary-label svg { color: var(--warning); }
        .chat-risk-primary.danger .chat-risk-primary-label svg { color: var(--danger); }
        .chat-risk-primary-value {
            display: flex;
            align-items: baseline;
            gap: 9px;
            margin: 12px 0 6px;
        }
        .chat-risk-primary-value strong {
            color: var(--text-primary);
            font-size: clamp(44px, 5vw, 60px);
            font-weight: 735;
            font-variant-numeric: tabular-nums;
            line-height: .95;
            letter-spacing: -.055em;
            transition:
                transform var(--motion-standard) var(--ease-standard),
                color var(--motion-standard) var(--ease-standard);
        }
        .chat-risk-primary:hover .chat-risk-primary-value strong {
            transform: translateY(-2px);
        }
        .chat-risk-primary.warning:hover .chat-risk-primary-value strong { color: var(--warning); }
        .chat-risk-primary.danger:hover .chat-risk-primary-value strong { color: var(--danger); }
        }
        .chat-risk-primary-value span {
            color: var(--text-secondary);
            font-size: 12px;
            font-weight: 620;
        }
        .chat-risk-primary-helper {
            color: var(--text-secondary);
            font-size: 12px;
            line-height: 1.5;
            text-wrap: pretty;
        }
        .chat-risk-context {
            min-width: 0;
            padding: 22px 26px 18px;
            transition: background-color var(--motion-standard) var(--ease-standard);
        }
        .chat-risk-context:hover {
            background: color-mix(in srgb, var(--primary-soft) 18%, var(--surface));
        }
        .chat-risk-context-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 14px;
            padding-bottom: 18px;
        }
        .chat-risk-data-mode {
            color: var(--text-tertiary);
            font-size: 11px;
            line-height: 18px;
            white-space: nowrap;
        }
        .chat-risk-scale {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            border-top: 1px solid var(--border);
        }
        .chat-risk-scale-item {
            position: relative;
            min-width: 0;
            padding: 16px 18px 4px 0;
            transition:
                transform var(--motion-fast) var(--ease-standard),
                background-color var(--motion-fast) var(--ease-standard),
                box-shadow var(--motion-fast) var(--ease-standard);
        }
        .chat-risk-scale-item:hover {
            transform: translateY(-2px);
            background: color-mix(in srgb, var(--primary-soft) 40%, transparent);
            box-shadow: inset 0 2px 0 color-mix(in srgb, var(--primary) 48%, transparent);
        }
        .chat-risk-scale-item + .chat-risk-scale-item {
            padding-left: 18px;
            border-left: 1px solid var(--border);
        }
        .chat-risk-scale-item span {
            display: block;
            color: var(--text-tertiary);
            font-size: 11px;
            line-height: 16px;
        }
        .chat-risk-scale-item strong {
            display: block;
            margin: 5px 0 4px;
            color: var(--text-primary);
            font-size: 25px;
            font-weight: 720;
            font-variant-numeric: tabular-nums;
            line-height: 1;
            transition: transform var(--motion-fast) var(--ease-standard);
        }
        .chat-risk-scale-item:hover strong {
            transform: translateY(-1px) scale(1.035);
        }
        .chat-risk-scale-item strong.danger { color: var(--danger); }
        .chat-risk-scale-item small {
            display: block;
            overflow: hidden;
            color: var(--text-secondary);
            font-size: 11px;
            line-height: 16px;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .chat-section-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 14px;
            margin: 8px 0 8px;
        }
        .chat-section-title {
            color: #1D1D1F;
            font-size: 20px;
            font-weight: 650;
            line-height: 28px;
        }
        .chat-section-caption {
            color: #6E6E73;
            font-size: 13px;
            margin-top: 2px;
        }
        .chat-zero-state {
            min-height: 78px;
            display: flex;
            align-items: center;
            padding: 0 18px;
            border-radius: 14px;
            border: 1px solid rgba(52, 199, 89, 0.22);
            background: rgba(52, 199, 89, 0.08);
            color: #1D1D1F;
            font-size: 14px;
        }
        .chat-focus-card {
            min-height: 204px;
            padding: 16px;
            border-radius: 14px;
            border: 1px solid rgba(0, 0, 0, 0.08);
            background: rgba(255, 255, 255, 0.86);
        }
        .chat-focus-title {
            color: #1D1D1F;
            font-size: 15px;
            font-weight: 650;
            margin-bottom: 12px;
        }
        .chat-focus-item {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            padding: 8px 0;
            border-bottom: 1px solid rgba(0, 0, 0, 0.06);
            color: #1D1D1F;
            font-size: 13px;
        }
        .chat-focus-item span:first-child {
            color: #6E6E73;
        }
        .chat-filter-shell {
            padding: 16px;
            border-radius: 14px;
            border: 1px solid rgba(0, 0, 0, 0.08);
            background: rgba(255, 255, 255, 0.74);
            margin: 16px 0;
        }
        .chat-calendar-title {
            color: #1D1D1F;
            font-size: 18px;
            font-weight: 650;
            line-height: 40px;
            margin: 0;
            text-align: center;
        }
        .chat-calendar {
            display: grid;
            grid-template-columns: repeat(7, minmax(42px, 1fr));
            gap: 8px;
            padding: 4px 0 8px;
        }
        .chat-calendar-weekday {
            color: #8A94A3;
            font-size: 12px;
            text-align: center;
        }
        .chat-calendar-day {
            min-height: 48px;
            border: 1px solid rgba(0, 0, 0, 0.08);
            border-radius: 10px;
            background: rgba(255, 255, 255, 0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            color: #1D1D1F;
        }
        .chat-calendar-day.today {
            border-color: #0071E3;
            background: rgba(0, 113, 227, 0.06);
        }
        .chat-calendar-day.empty {
            background: transparent;
            border-color: transparent;
        }
        .chat-calendar-risk {
            min-width: 18px;
            height: 18px;
            padding: 0 6px;
            border-radius: 999px;
            background: #FF3B30;
            color: #fff;
            font-size: 11px;
            line-height: 18px;
            text-align: center;
        }
        .chat-detail-panel {
            padding: 18px;
            border-radius: 16px;
            border: 1px solid rgba(0, 0, 0, 0.08);
            background: rgba(255, 255, 255, 0.88);
        }
        .chat-detail-heading {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
        }
        .chat-detail-eyebrow {
            color: #8A94A3;
            font-size: 11px;
            font-weight: 650;
            letter-spacing: 0.06em;
            margin-bottom: 3px;
        }
        .chat-detail-title {
            color: #1D1D1F;
            font-size: 18px;
            font-weight: 650;
            line-height: 24px;
        }
        .chat-detail-meta,
        .chat-detail-meta-row {
            color: #6E6E73;
            font-size: 12px;
            line-height: 20px;
            margin-bottom: 12px;
        }
        .chat-detail-meta-row {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 6px 10px;
            margin-top: 10px;
        }
        .chat-status-chip,
        .chat-risk-chip {
            display: inline-flex;
            align-items: center;
            min-height: 24px;
            padding: 2px 9px;
            border: 1px solid transparent;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 650;
            line-height: 16px;
            white-space: nowrap;
        }
        .chat-status-chip.pending {
            color: var(--warning);
            background: var(--warning-soft);
            border-color: color-mix(in srgb, var(--warning) 24%, var(--border));
        }
        .chat-status-chip.resolved {
            color: var(--success);
            background: var(--success-soft);
            border-color: color-mix(in srgb, var(--success) 24%, var(--border));
        }
        .chat-status-chip.ignored {
            color: var(--text-secondary);
            background: var(--surface-muted);
            border-color: var(--border);
        }
        .chat-risk-chip.high {
            color: var(--danger);
            background: var(--danger-soft);
        }
        .chat-risk-chip.medium {
            color: var(--warning);
            background: var(--warning-soft);
        }
        .chat-risk-chip.low {
            color: var(--text-secondary);
            background: var(--surface-muted);
        }
        .chat-detail-message {
            padding: 14px;
            border-radius: 12px;
            background: rgba(245, 247, 250, 0.92);
            border: 1px solid rgba(0, 0, 0, 0.06);
            color: #1D1D1F;
            font-size: 14px;
            line-height: 22px;
            white-space: pre-wrap;
            text-wrap: pretty;
        }
        .chat-detail-message > span {
            display: block;
            color: #8A94A3;
            font-size: 11px;
            font-weight: 650;
            line-height: 16px;
            margin-bottom: 6px;
            white-space: normal;
        }
        .chat-detail-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            margin-top: 12px;
        }
        .chat-detail-cell {
            padding: 10px 12px;
            border-radius: 12px;
            background: rgba(245, 247, 250, 0.75);
            color: #1D1D1F;
            font-size: 13px;
        }
        .chat-detail-cell span {
            display: block;
            color: #8A94A3;
            font-size: 12px;
            margin-bottom: 4px;
        }
        .chat-detail-cell strong {
            display: block;
            font-size: 13px;
            font-weight: 600;
            line-height: 19px;
            overflow-wrap: anywhere;
        }
        .chat-detail-cell.user-id strong {
            font-size: 12px;
            font-variant-numeric: tabular-nums;
        }
        .chat-focus-card,
        .chat-detail-panel {
            background: var(--surface);
            border-color: var(--border);
            border-radius: var(--radius-card);
        }
        .chat-section-caption,
        .chat-detail-meta { color: var(--text-secondary); }
        .chat-detail-cell span { color: var(--text-tertiary); }
        .chat-section-title,
        .chat-focus-title,
        .chat-detail-title,
        .chat-detail-cell { color: var(--text-primary); }
        .chat-section-title { font-size: 18px; line-height: 26px; }
        .chat-zero-state {
            color: var(--success);
            background: var(--success-soft);
            border-color: color-mix(in srgb, var(--success) 24%, var(--border));
            border-radius: var(--radius-card);
        }
        div.stVerticalBlock.st-key-chat_filter_panel {
            gap: 16px;
            margin: 12px 0 24px;
            padding: 17px 0 14px;
            border-top: 1px solid var(--border-strong);
            border-bottom: 1px solid var(--border);
            animation: chat-workspace-enter var(--motion-enter) var(--ease-standard) both;
        }
        .chat-filter-head,
        .chat-result-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
        }
        .chat-filter-head { margin-bottom: 2px; }
        .chat-filter-title {
            color: var(--text-primary);
            font-size: 18px;
            font-weight: 680;
            line-height: 26px;
            letter-spacing: -.015em;
        }
        .chat-filter-caption {
            color: var(--text-secondary);
            font-size: 12px;
            line-height: 18px;
            margin-top: 4px;
            text-wrap: pretty;
        }
        .chat-filter-mode {
            color: var(--text-tertiary);
            font-size: 11px;
            font-weight: 650;
            letter-spacing: .04em;
            white-space: nowrap;
        }
        div.stVerticalBlock.st-key-chat_filter_command_bar {
            gap: 10px;
            padding: 14px 16px 12px;
            border: 1px solid color-mix(in srgb, var(--primary) 14%, var(--border));
            border-radius: var(--radius-card);
            background: color-mix(in srgb, var(--primary-soft) 18%, var(--surface));
            box-shadow: inset 0 1px 0 color-mix(in srgb, white 68%, transparent);
        }
        div.stVerticalBlock.st-key-chat_filter_command_bar [data-baseweb="input"] > div,
        div.stVerticalBlock.st-key-chat_filter_command_bar [data-baseweb="select"] > div {
            background: color-mix(in srgb, var(--surface) 88%, transparent);
        }
        div.stVerticalBlock.st-key-chat_filter_drawer {
            gap: 0;
            margin-top: 2px;
            padding-top: 4px;
            border-top: 1px solid color-mix(in srgb, var(--border) 82%, transparent);
        }
        [class*="st-key-chat_filter_drawer"] details {
            border: 0 !important;
            border-radius: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
        }
        [class*="st-key-chat_filter_drawer"] details summary {
            min-height: 42px;
            padding: 0 2px !important;
            color: var(--text-secondary);
            transition: color var(--motion-standard) var(--ease-standard);
        }
        [class*="st-key-chat_filter_drawer"] details summary:hover {
            color: var(--primary);
        }
        [class*="st-key-chat_filter_drawer"] details[open] summary {
            border-bottom: 1px solid var(--border);
            color: var(--text-primary);
        }
        [class*="st-key-chat_filter_drawer"] details > div {
            padding: 14px 0 2px !important;
        }
        .chat-result-title {
            color: var(--text-primary);
            font-size: 17px;
            font-weight: 680;
            line-height: 24px;
            letter-spacing: -.012em;
        }
        .chat-result-caption {
            max-width: 620px;
            color: var(--text-secondary);
            font-size: 12px;
            line-height: 18px;
            margin-top: 2px;
            text-wrap: pretty;
        }
        .chat-result-range {
            display: inline-flex;
            align-items: center;
            min-height: 34px;
            padding-left: 18px;
            border-left: 1px solid var(--border);
            color: var(--text-primary);
            font-size: 12px;
            font-weight: 640;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }
        .chat-result-divider {
            height: 1px;
            background: color-mix(in srgb, var(--border) 78%, transparent);
        }
        div.stVerticalBlock.st-key-chat_result_panel {
            gap: 18px;
            padding: 18px 0 0;
            border-top: 1px solid var(--border-strong);
            background: transparent;
            box-shadow: none;
            animation: chat-workspace-enter var(--motion-enter) var(--ease-standard) both;
        }
        div.stVerticalBlock.st-key-chat_trend_workspace {
            gap: 10px;
            margin: 18px 0 0;
            padding: 0 0 2px;
        }
        div.stVerticalBlock.st-key-chat_trend_card {
            gap: 16px;
            padding: 20px 20px 16px;
            border: 1px solid var(--border);
            border-radius: var(--radius-panel);
            background: var(--surface);
            box-shadow: var(--shadow-1);
        }
        .chat-trend-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 16px;
        }
        .chat-trend-legend {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            flex-wrap: wrap;
            gap: 7px 12px;
            max-width: 280px;
            padding-top: 3px;
            color: var(--text-secondary);
            font-size: 11px;
            line-height: 18px;
        }
        .chat-trend-legend span {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            white-space: nowrap;
        }
        .chat-trend-legend i {
            display: inline-block;
            width: 7px;
            height: 7px;
            border-radius: 2px;
            background: var(--text-tertiary);
        }
        .chat-trend-legend i.danger { background: var(--danger); }
        .chat-trend-legend i.warning { background: var(--warning); }
        .chat-trend-legend i.muted { background: var(--risk-low); }
        .chat-trend-summary {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            padding: 11px 0;
            border-top: 1px solid var(--border);
            border-bottom: 1px solid var(--border);
        }
        .chat-trend-summary > div {
            min-width: 0;
            padding: 0 14px;
        }
        .chat-trend-summary > div:first-child { padding-left: 0; }
        .chat-trend-summary > div + div { border-left: 1px solid var(--border); }
        .chat-trend-summary span {
            display: block;
            color: var(--text-tertiary);
            font-size: 10px;
            font-weight: 640;
            line-height: 15px;
        }
        .chat-trend-summary strong {
            display: block;
            overflow: hidden;
            margin-top: 3px;
            color: var(--text-primary);
            font-size: 19px;
            font-weight: 720;
            font-variant-numeric: tabular-nums;
            line-height: 24px;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .chat-trend-summary strong.danger { color: var(--danger); }
        .chat-trend-summary strong.up {
            color: var(--primary-hover);
            font-size: 15px;
            font-weight: 680;
        }
        .chat-trend-summary strong.down { color: var(--success); }
        .chat-trend-summary strong.neutral {
            color: var(--text-secondary);
            font-size: 13px;
            font-weight: 650;
        }
        [class*="st-key-chat_trend_card"] [data-testid="stVegaLiteChart"] {
            transition: filter var(--motion-standard) var(--ease-standard);
        }
        .chat-focus-card {
            min-height: 426px;
            padding: 20px;
            box-shadow: var(--shadow-1);
        }
        .chat-focus-title {
            margin-bottom: 14px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--border);
        }
        .chat-focus-priority {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 2px 12px;
            align-items: center;
            padding: 12px;
            margin-bottom: 6px;
            border: 1px solid var(--border);
            border-radius: var(--radius-control);
            background: var(--surface-muted);
        }
        .chat-focus-priority.danger {
            border-color: color-mix(in srgb, var(--danger) 22%, var(--border));
            background: color-mix(in srgb, var(--danger-soft) 52%, var(--surface));
        }
        .chat-focus-priority span,
        .chat-focus-priority small {
            color: var(--text-secondary);
            font-size: 11px;
            line-height: 16px;
        }
        .chat-focus-priority strong {
            grid-column: 2;
            grid-row: 1 / span 2;
            color: var(--text-primary);
            font-size: 28px;
            font-weight: 740;
            font-variant-numeric: tabular-nums;
            line-height: 32px;
        }
        .chat-focus-priority.danger strong { color: var(--danger); }
        .chat-focus-item strong.numeric {
            font-size: 17px;
            font-weight: 720;
            font-variant-numeric: tabular-nums;
        }
        .chat-focus-chip {
            overflow: hidden;
            max-width: 58%;
            padding: 2px 8px;
            border: 1px solid var(--border);
            border-radius: var(--radius-pill);
            background: var(--surface-muted);
            color: var(--text-primary);
            font-size: 11px;
            font-weight: 650;
            line-height: 18px;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .chat-focus-latest {
            padding-top: 10px;
        }
        .chat-focus-latest span {
            display: block;
            margin-bottom: 5px;
            color: var(--text-tertiary);
            font-size: 11px;
            line-height: 16px;
        }
        .chat-focus-latest strong {
            display: -webkit-box;
            overflow: hidden;
            color: var(--text-primary);
            font-size: 12px;
            font-weight: 560;
            line-height: 18px;
            text-wrap: pretty;
            -webkit-box-orient: vertical;
            -webkit-line-clamp: 2;
        }
        [class*="st-key-chat_records_workspace"] {
            animation: chat-workspace-enter var(--motion-enter) var(--ease-standard) both;
        }
        [class*="st-key-chat_records_workspace"] > [data-testid="stVerticalBlockBorderWrapper"] {
            position: relative;
            padding: 16px;
            border: 1px solid color-mix(in srgb, var(--border-strong) 72%, transparent);
            border-radius: var(--radius-panel);
            background: color-mix(in srgb, var(--surface) 78%, transparent);
            box-shadow: var(--shadow-1);
            backdrop-filter: blur(18px) saturate(1.08);
            -webkit-backdrop-filter: blur(18px) saturate(1.08);
            overflow: hidden;
        }
        [class*="st-key-chat_records_workspace"] > [data-testid="stVerticalBlockBorderWrapper"]::before {
            content: "";
            position: absolute;
            inset: 0 0 auto;
            height: 1px;
            background: color-mix(in srgb, white 72%, transparent);
            pointer-events: none;
        }
        [class*="st-key-chat_records_workspace"] button,
        [class*="st-key-chat_records_workspace"] a,
        [class*="st-key-chat_records_workspace"] [data-baseweb="select"] > div {
            transition:
                transform var(--motion-fast) var(--ease-standard),
                border-color var(--motion-standard) var(--ease-standard),
                background-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        [class*="st-key-chat_records_workspace"] button:active,
        [class*="st-key-chat_records_workspace"] a:active {
            transform: scale(0.985);
        }
        [class*="st-key-chat_risk_drawer"] {
            margin-bottom: 2px;
        }
        [class*="st-key-chat_risk_drawer"] details {
            border-color: color-mix(in srgb, var(--border-strong) 78%, transparent) !important;
            background: color-mix(in srgb, var(--surface) 78%, transparent) !important;
            backdrop-filter: blur(14px) saturate(1.05);
            -webkit-backdrop-filter: blur(14px) saturate(1.05);
            transition:
                border-color var(--motion-standard) var(--ease-standard),
                background-color var(--motion-standard) var(--ease-standard);
        }
        [class*="st-key-chat_risk_drawer"] details[open] {
            border-color: color-mix(in srgb, var(--primary) 20%, var(--border-strong)) !important;
            background: color-mix(in srgb, var(--surface) 92%, var(--primary-soft)) !important;
        }
        [class*="st-key-chat_risk_drawer"] details[open] summary {
            border-bottom: 1px solid color-mix(in srgb, var(--border) 78%, transparent);
        }
        [class*="st-key-chat_risk_drawer"] details > div {
            padding: 12px 16px 14px !important;
        }
        .chat-selection-note {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding: 9px 12px;
            margin-top: 8px;
            border: 1px solid var(--border);
            border-radius: var(--radius-control);
            background: color-mix(in srgb, var(--surface-muted) 76%, transparent);
            color: var(--text-secondary);
            font-size: 12px;
            line-height: 18px;
        }
        .chat-selection-note strong {
            color: var(--text-primary);
            font-weight: 680;
        }
        [class*="st-key-chat_records_workspace"] .chat-detail-panel {
            background: color-mix(in srgb, var(--surface) 74%, transparent);
            border-color: color-mix(in srgb, var(--border-strong) 70%, transparent);
            box-shadow: inset 0 1px 0 color-mix(in srgb, white 78%, transparent), var(--shadow-1);
            backdrop-filter: blur(16px) saturate(1.06);
            -webkit-backdrop-filter: blur(16px) saturate(1.06);
            transition:
                transform var(--motion-standard) var(--ease-standard),
                border-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        [class*="st-key-chat_records_workspace"] .chat-detail-panel:hover {
            transform: translateY(-1px);
            border-color: color-mix(in srgb, var(--primary) 22%, var(--border));
            box-shadow: var(--shadow-2);
        }
        [class*="st-key-chat_records_workspace"] .chat-detail-message,
        [class*="st-key-chat_records_workspace"] .chat-detail-cell {
            background: color-mix(in srgb, var(--surface-muted) 72%, transparent);
        }
        [class*="st-key-chat_detail_actions"] {
            margin-top: 10px;
            padding: 0 2px;
        }
        [class*="st-key-chat_detail_actions"] [data-testid="stHorizontalBlock"] {
            gap: 8px;
        }
        [class*="st-key-chat_detail_actions"] button,
        [class*="st-key-chat_detail_actions"] a {
            min-height: 40px;
            white-space: nowrap;
            transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
        }
        [class*="st-key-chat_detail_actions"] button:active,
        [class*="st-key-chat_detail_actions"] a:active {
            transform: scale(0.985);
        }
        .chat-moderation-head {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 14px;
            margin: -2px 0 14px;
            padding: 0 2px 14px;
            border-bottom: 1px solid var(--border);
        }
        .chat-moderation-title {
            color: var(--text-primary);
            font-size: 16px;
            font-weight: 680;
            line-height: 24px;
        }
        .chat-moderation-meta {
            color: var(--text-secondary);
            font-size: 12px;
            line-height: 18px;
            text-align: right;
            max-width: 42%;
            overflow-wrap: anywhere;
        }
        .chat-moderation-meta strong {
            color: var(--text-primary);
            font-weight: 650;
        }
        .chat-calendar-day,
        .chat-detail-message,
        .chat-detail-cell {
            border-color: var(--border);
            background: var(--surface-muted);
        }
        .chat-calendar-day.today {
            border-color: var(--primary);
            background: var(--primary-soft);
        }
        .chat-calendar-risk { background: var(--danger); }
        @media (max-width: 900px) {
            .chat-risk-pulse { grid-template-columns: 1fr; }
            .chat-risk-primary { border-right: 0; border-bottom: 1px solid var(--border); }
            div.stVerticalBlock.st-key-chat_trend_workspace [data-testid="stHorizontalBlock"] {
                flex-direction: column;
            }
            div.stVerticalBlock.st-key-chat_trend_workspace [data-testid="stColumn"] {
                width: 100% !important;
                flex: 1 1 100% !important;
            }
            .chat-focus-card { min-height: auto; }
            .chat-detail-grid {
                grid-template-columns: 1fr;
            }
            .chat-detail-panel { padding: 16px; }
            div.stVerticalBlock.st-key-chat_filter_command_bar { padding: 14px; }
            [class*="st-key-chat_records_workspace"] > [data-testid="stVerticalBlockBorderWrapper"] {
                padding: 12px;
            }
        }
        @media (max-width: 560px) {
            .chat-risk-primary,
            .chat-risk-context { padding: 18px; }
            .chat-risk-context-head { align-items: flex-start; flex-direction: column; gap: 6px; }
            .chat-risk-scale { grid-template-columns: 1fr; }
            .chat-risk-scale-item,
            .chat-risk-scale-item + .chat-risk-scale-item {
                display: grid;
                grid-template-columns: minmax(0, 1fr) auto;
                gap: 2px 12px;
                align-items: center;
                padding: 12px 0;
                border-left: 0;
                border-bottom: 1px solid var(--border);
            }
            .chat-risk-scale-item:last-child { border-bottom: 0; }
            .chat-risk-scale-item strong { grid-column: 2; grid-row: 1 / span 2; margin: 0; }
            .chat-risk-scale-item small { white-space: normal; }
            .chat-section-head { align-items: flex-start; flex-direction: column; }
            .chat-trend-header { flex-direction: column; gap: 10px; }
            .chat-trend-legend { justify-content: flex-start; max-width: none; }
            .chat-trend-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .chat-trend-summary > div { padding: 8px 12px; }
            .chat-trend-summary > div:first-child { padding-left: 12px; }
            .chat-trend-summary > div:nth-child(3) {
                border-left: 0;
                border-top: 1px solid var(--border);
            }
            .chat-trend-summary > div:nth-child(4) { border-top: 1px solid var(--border); }
            .chat-filter-head,
            .chat-result-head { flex-direction: column; gap: 8px; }
            .chat-filter-head,
            .chat-result-head { align-items: flex-start; }
            .chat-result-range {
                min-height: auto;
                padding: 0;
                border-left: 0;
                color: var(--text-secondary);
            }
            div.stVerticalBlock.st-key-chat_filter_panel { padding-top: 14px; }
            div.stVerticalBlock.st-key-chat_result_panel { padding-top: 14px; }
            .chat-calendar { gap: 4px; }
            .chat-calendar-day { min-height: 42px; }
            .chat-detail-heading { align-items: center; }
            .chat-moderation-head { align-items: flex-start; flex-direction: column; gap: 6px; }
            .chat-moderation-meta { max-width: 100%; text-align: left; }
        }
        @media (prefers-reduced-motion: reduce) {
            .chat-risk-pulse,
            .chat-risk-primary,
            .chat-risk-primary::after,
            .chat-risk-primary-label svg,
            .chat-risk-context,
            .chat-risk-context-label svg,
            .chat-risk-primary-value strong,
            .chat-risk-scale-item,
            .chat-risk-scale-item strong,
            div.stVerticalBlock.st-key-chat_filter_panel,
            div.stVerticalBlock.st-key-chat_result_panel,
            [class*="st-key-chat_records_workspace"],
            [class*="st-key-chat_trend_card"] [data-testid="stVegaLiteChart"],
            [class*="st-key-chat_records_workspace"] *,
            [class*="st-key-chat_detail_actions"] button,
            [class*="st-key-chat_detail_actions"] a {
                animation: none !important;
                transition: none;
            }
            .chat-risk-pulse:hover,
            .chat-risk-primary:hover .chat-risk-primary-label svg,
            .chat-risk-context:hover .chat-risk-context-label svg,
            .chat-risk-primary:hover .chat-risk-primary-value strong,
            .chat-risk-scale-item:hover,
            .chat-risk-scale-item:hover strong {
                transform: none !important;
            }
        }
        @keyframes chat-workspace-enter {
            from {
                opacity: 0;
                transform: translateY(8px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        @keyframes chat-chart-enter {
            from { opacity: 0; transform: translateY(4px); }
            to { opacity: 1; transform: translateY(0); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_overview(
    st,
    today_count: int,
    yesterday_count: int,
    week_count: int,
    high_pending_count: int,
    pending_count: int,
    merge_duplicates: bool,
) -> None:
    delta = today_count - yesterday_count
    delta_text = "较昨日持平" if delta == 0 else f"较昨日 {'+' if delta > 0 else ''}{delta}"
    if high_pending_count:
        tone = "danger"
        queue_summary = f"其中 {high_pending_count} 条为未处理高风险，请优先核查。"
    elif pending_count:
        tone = "warning"
        queue_summary = "当前没有未处理高风险，仍有普通风险记录等待处理。"
    else:
        tone = "clear"
        queue_summary = "当前风险队列已经清空。"
    data_mode = "已合并疑似重复记录" if merge_duplicates else "保留疑似重复记录"
    st.markdown(
        f"""
        <section class="chat-risk-pulse" aria-label="风险态势概览">
            <div class="chat-risk-primary {tone}">
                <div>
                    <div class="chat-risk-primary-label">{icon_svg('alert')} 近 30 日待处理</div>
                    <div class="chat-risk-primary-value"><strong>{pending_count}</strong><span>条风险记录</span></div>
                </div>
                <div class="chat-risk-primary-helper">{escape(queue_summary)}</div>
            </div>
            <div class="chat-risk-context">
                <div class="chat-risk-context-head">
                    <div class="chat-risk-context-label">{icon_svg('bar')} 风险节奏</div>
                    <div class="chat-risk-data-mode">{escape(data_mode)}</div>
                </div>
                <div class="chat-risk-scale">
                    <div class="chat-risk-scale-item">
                        <span>今日风险</span>
                        <strong>{today_count}</strong>
                        <small>{escape(delta_text)}</small>
                    </div>
                    <div class="chat-risk-scale-item">
                        <span>近 7 日风险</span>
                        <strong>{week_count}</strong>
                        <small>日均 {week_count / 7:.1f} 条</small>
                    </div>
                    <div class="chat-risk-scale-item">
                        <span>未处理高风险</span>
                        <strong class="{'danger' if high_pending_count else ''}">{high_pending_count}</strong>
                        <small>{'需要优先核查' if high_pending_count else '当前无高风险积压'}</small>
                    </div>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _risk_trend_dataframe(records: list[dict], start_date: date, end_date: date) -> pd.DataFrame:
    rows = []
    day_count = (end_date - start_date).days + 1
    for offset in range(day_count):
        current = start_date + timedelta(days=offset)
        day_records = [
            record
            for record in records
            if (_parse_created_time(record.get("created_time")) or datetime.min).date() == current
        ]
        for level in ("高风险", "中风险", "低风险"):
            rows.append(
                {
                    "日期": current.isoformat(),
                    "风险等级": level,
                    "数量": sum(1 for record in day_records if record.get("risk_level") == level),
                }
            )
    return pd.DataFrame(rows)


def _risk_trend_daily_dataframe(records: list[dict], start_date: date, end_date: date) -> pd.DataFrame:
    trend_df = _risk_trend_dataframe(records, start_date, end_date)
    daily = (
        trend_df.pivot(index="日期", columns="风险等级", values="数量")
        .reset_index()
        .rename_axis(None, axis=1)
    )
    for level in ("高风险", "中风险", "低风险"):
        if level not in daily:
            daily[level] = 0
        daily[level] = daily[level].fillna(0).astype(int)

    daily["风险总量"] = daily[["高风险", "中风险", "低风险"]].sum(axis=1).astype(int)
    daily["完整日期"] = daily["日期"]
    daily["日期"] = pd.to_datetime(daily["日期"])
    for level in ("高风险", "中风险", "低风险"):
        percentages = [
            (int(count) / int(total) * 100) if int(total) else 0
            for count, total in zip(daily[level], daily["风险总量"], strict=True)
        ]
        daily[f"{level}占比"] = percentages
        daily[f"{level}明细"] = [
            f"{int(count)} 条 · {percentage:.0f}%"
            for count, percentage in zip(daily[level], percentages, strict=True)
        ]

    rolling_average = daily["风险总量"].shift(1).rolling(window=7, min_periods=3).mean()
    enough_history = rolling_average.notna()
    positive_baseline_spike = (
        (rolling_average > 0)
        & (daily["风险总量"] > rolling_average * 1.8)
        & (daily["风险总量"] >= rolling_average + 2)
    )
    zero_baseline_spike = (rolling_average == 0) & (daily["风险总量"] >= 3)
    daily["异常峰值"] = (enough_history & (positive_baseline_spike | zero_baseline_spike)).fillna(False)
    return daily


def _period_change_label(current_total: int, previous_total: int | None) -> tuple[str, str]:
    if previous_total is None:
        return "暂无上期数据", "neutral"
    if previous_total == 0:
        if current_total == 0:
            return "与上期持平", "neutral"
        return "上期为 0", "up"

    percentage = (current_total - previous_total) / previous_total * 100
    if abs(percentage) < 0.5:
        return "与上期持平", "neutral"
    direction = "↑" if percentage > 0 else "↓"
    tone = "up" if percentage > 0 else "down"
    return f"{direction} {abs(percentage):.0f}%", tone


def _risk_date_tick_values(daily: pd.DataFrame, max_ticks: int = 8) -> list[pd.Timestamp]:
    """Prioritize dates with risk events, then add sparse period references."""
    if daily.empty or max_ticks <= 0:
        return []

    risk_positions = [
        index for index, total in enumerate(daily["风险总量"].tolist()) if int(total) > 0
    ]
    if len(risk_positions) <= max_ticks:
        selected = set(risk_positions)
    else:
        peak_position = int(daily["风险总量"].idxmax())
        selected = {risk_positions[0], risk_positions[-1], peak_position}
        candidates = [position for position in risk_positions if position not in selected]
        slots = max_ticks - len(selected)
        if slots == 1 and candidates:
            selected.add(candidates[len(candidates) // 2])
        elif slots > 1 and candidates:
            for slot in range(slots):
                candidate_index = round(slot * (len(candidates) - 1) / (slots - 1))
                selected.add(candidates[candidate_index])

    reference_target = min(max_ticks, min(len(daily), 6))
    if len(selected) < reference_target:
        reference_slots = max(reference_target - len(selected), 1)
        for slot in range(reference_slots + 2):
            position = round(slot * (len(daily) - 1) / max(reference_slots + 1, 1))
            selected.add(position)
            if len(selected) >= reference_target:
                break

    return [pd.Timestamp(daily.iloc[position]["日期"]) for position in sorted(selected)[:max_ticks]]


def _risk_axis_max(peak_total: int) -> int:
    """Keep both risk charts on the same readable integer scale with headroom."""
    return max(1, math.ceil(max(peak_total, 0) * 1.12))


def _render_focus_card(st, db_path, records: list[dict], start_date: date, end_date: date) -> None:
    is_today = start_date == end_date == date.today()
    high_pending = [record for record in records if record.get("risk_level") == "高风险" and record.get("status") == "待处理"]
    user_counts: dict[str, int] = {}
    keyword_counts: dict[str, int] = {}
    for record in records:
        user = str(record.get("discord_user_id") or "未知用户")
        user_counts[user] = user_counts.get(user, 0) + 1
        for word in str(record.get("message") or "").lower().replace("!", " ").replace(".", " ").split():
            if len(word) >= 4:
                keyword_counts[word] = keyword_counts.get(word, 0) + 1

    top_user_id = max(user_counts.items(), key=lambda item: item[1])[0] if user_counts else ""
    top_user_record = next(
        (record for record in records if str(record.get("discord_user_id") or "") == top_user_id),
        None,
    )
    if top_user_record:
        top_user_names = _resolved_record_identities(st, db_path, top_user_record)
        top_user = top_user_names.get(top_user_id) or "未知用户"
    else:
        top_user = "-"
    top_keyword = max(keyword_counts.items(), key=lambda item: item[1])[0] if keyword_counts else "-"
    latest_high = next((record for record in records if record.get("risk_level") == "高风险"), None)
    latest_full_text = str(latest_high.get("message") or "") if latest_high else "暂无高风险记录"
    latest_text = _short_text(latest_full_text, 96)
    attention_class = " danger" if high_pending else " clear"
    st.markdown(
        f"""
        <div class="chat-focus-card">
            <div class="chat-focus-title">{'今日重点关注' if is_today else '范围重点关注'}</div>
            <div class="chat-focus-priority{attention_class}">
                <span>未处理高风险</span>
                <strong>{len(high_pending)}</strong>
                <small>{'需要优先核查' if high_pending else '当前没有高风险积压'}</small>
            </div>
            <div class="chat-focus-item"><span>{'今日风险' if is_today else '范围风险'}</span><strong class="numeric">{len(records)}</strong></div>
            <div class="chat-focus-item"><span>风险最多用户</span><strong class="chat-focus-chip">{escape(top_user)}</strong></div>
            <div class="chat-focus-item"><span>高频关键词</span><strong class="chat-focus-chip">{escape(top_keyword)}</strong></div>
            <div class="chat-focus-latest">
                <span>最新高风险</span>
                <strong title="{escape(latest_full_text, quote=True)}">{escape(latest_text)}</strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_trend(
    st,
    start_date: date,
    end_date: date,
    records: list[dict],
    previous_total: int | None = None,
) -> None:
    daily = _risk_trend_daily_dataframe(records, start_date, end_date)
    total = int(daily["风险总量"].sum()) if not daily.empty else 0
    high_total = int(daily["高风险"].sum()) if not daily.empty else 0
    peak_total = int(daily["风险总量"].max()) if not daily.empty else 0
    change_label, change_tone = _period_change_label(total, previous_total)

    with st.container(key="chat_trend_card"):
        st.markdown(
            """
            <div class="chat-trend-header">
                <div>
                    <div class="chat-section-title">风险趋势</div>
                    <div class="chat-section-caption">先看每日总量峰值，再看高、中、低风险构成。</div>
                </div>
                <div class="chat-trend-legend" aria-label="图例">
                    <span><i class="danger"></i>高风险</span>
                    <span><i class="warning"></i>中风险</span>
                    <span><i class="muted"></i>低风险</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <div class="chat-trend-summary">
                <div><span>周期风险</span><strong>{total}</strong></div>
                <div><span>高风险</span><strong class="danger">{high_total}</strong></div>
                <div><span>风险峰值</span><strong>{peak_total}</strong></div>
                <div><span>较上周期</span><strong class="{change_tone}">{escape(change_label)}</strong></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if total == 0:
            st.markdown(
                '<div class="chat-zero-state">当前日期与筛选范围内未检测到风险言论，社区聊天状态稳定。</div>',
                unsafe_allow_html=True,
            )
            return

        level_columns = ["高风险", "中风险", "低风险"]
        trend_df = daily.melt(
            id_vars=[
                "日期",
                "完整日期",
                "风险总量",
                "高风险明细",
                "中风险明细",
                "低风险明细",
                "异常峰值",
            ],
            value_vars=level_columns,
            var_name="风险等级",
            value_name="数量",
        )
        trend_df["堆叠顺序"] = trend_df["风险等级"].map(
            {"低风险": 0, "中风险": 1, "高风险": 2}
        )
        shared_y_max = _risk_axis_max(peak_total)
        band_gap = max(2, math.ceil(shared_y_max * 0.18))
        line_offset = shared_y_max + band_gap
        chart_y_max = line_offset + shared_y_max
        daily["总量绘图值"] = daily["风险总量"] + line_offset
        peak_days = daily[(daily["风险总量"] == peak_total) & (daily["风险总量"] > 0)]
        hover = alt.selection_point(
            name="risk_date_hover",
            fields=["日期"],
            on="pointerover",
            clear="pointerout",
            empty=False,
        )
        day_count = max((end_date - start_date).days + 1, 1)
        tick_values = _risk_date_tick_values(daily, max_ticks=8)
        bar_size = 28 if day_count <= 7 else 14 if day_count <= 14 else 9
        domain_start = datetime.combine(start_date, datetime.min.time()) - timedelta(hours=12)
        domain_end = datetime.combine(end_date, datetime.min.time()) + timedelta(hours=12)
        x_scale = alt.Scale(domain=[domain_start, domain_end], nice=False)
        shared_x = alt.X(
            "日期:T",
            title=None,
            scale=x_scale,
            axis=alt.Axis(
                values=tick_values,
                format="%-m/%-d",
                labelAngle=0,
                labelColor=COLORS["text_secondary"],
                labelFontWeight=600,
                labelOverlap="greedy",
                labelSeparation=8,
                labelPadding=10,
                domain=False,
                ticks=False,
                grid=False,
            ),
        )
        tick_step = max(1, math.ceil(shared_y_max / 5))
        band_ticks = list(range(0, shared_y_max + 1, tick_step))
        if band_ticks[-1] != shared_y_max:
            band_ticks.append(shared_y_max)
        axis_tick_values = band_ticks + [line_offset + value for value in band_ticks]
        full_y_scale = alt.Scale(domain=[0, chart_y_max], nice=False)
        y_axis = alt.Axis(
            title="风险数",
            titleColor=COLORS["text_secondary"],
            titleFontSize=11,
            titleFontWeight=600,
            titlePadding=12,
            values=axis_tick_values,
            labelExpr=f"datum.value >= {line_offset} ? format(datum.value - {line_offset}, '.0f') : format(datum.value, '.0f')",
            labelColor=COLORS["text_secondary"],
            labelFontSize=11,
            labelPadding=7,
            domain=False,
            ticks=False,
            grid=True,
            gridColor=COLORS["border"],
            gridOpacity=0.62,
            gridWidth=1,
        )
        line_y = alt.Y(
            "总量绘图值:Q",
            title="风险数",
            scale=full_y_scale,
            axis=y_axis,
        )
        stack_y = alt.Y(
            "数量:Q",
            title="风险数",
            stack="zero",
            scale=full_y_scale,
            axis=y_axis,
        )
        axis_carrier = (
            alt.Chart(pd.DataFrame({"轴刻度范围": [0, chart_y_max]}))
            .mark_point(opacity=0)
            .encode(
                y=alt.Y("轴刻度范围:Q", scale=full_y_scale, axis=y_axis),
                x=alt.value(0),
            )
        )
        divider = (
            alt.Chart(pd.DataFrame({"分隔位置": [shared_y_max + band_gap / 2]}))
            .mark_rule(color=COLORS["border_strong"], strokeWidth=1, strokeDash=[4, 5], opacity=0.8)
            .encode(y=alt.Y("分隔位置:Q", scale=full_y_scale, axis=y_axis))
        )
        top_band_label = (
            alt.Chart(pd.DataFrame({"标签": ["总风险趋势"], "位置": [chart_y_max - 0.35]}))
            .mark_text(
                align="left",
                baseline="top",
                color=COLORS["primary"],
                fontSize=11,
                fontWeight=600,
            )
            .encode(
                x=alt.value(8),
                y=alt.Y("位置:Q", scale=full_y_scale, axis=y_axis),
                text="标签:N",
            )
        )
        lower_band_label = (
            alt.Chart(pd.DataFrame({"标签": ["风险等级构成"], "位置": [shared_y_max - 0.35]}))
            .mark_text(
                align="left",
                baseline="top",
                color=COLORS["text_secondary"],
                fontSize=11,
                fontWeight=600,
            )
            .encode(
                x=alt.value(8),
                y=alt.Y("位置:Q", scale=full_y_scale, axis=y_axis),
                text="标签:N",
            )
        )
        bars = (
            alt.Chart(trend_df)
            .mark_bar(size=bar_size, cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=shared_x,
                y=stack_y,
                color=alt.Color(
                    "风险等级:N",
                    scale=alt.Scale(
                        domain=level_columns,
                        range=[COLORS["danger"], COLORS["warning"], COLORS["risk_low"]],
                    ),
                    legend=None,
                ),
                opacity=alt.condition(hover, alt.value(1), alt.value(0.30), empty=True),
                order=alt.Order("堆叠顺序:Q", sort="ascending"),
            )
        )
        line = (
            alt.Chart(daily)
            .mark_line(
                color=COLORS["primary"],
                strokeWidth=2.7,
                strokeCap="round",
                strokeJoin="round",
            )
            .encode(x=shared_x, y=line_y)
        )
        nonzero_points = (
            alt.Chart(daily[daily["风险总量"] > 0])
            .mark_point(
                stroke=COLORS["primary"],
                fill=COLORS["card"],
                filled=True,
                size=30,
                strokeWidth=1.8,
            )
            .encode(x=shared_x, y=line_y)
        )
        peak_points = (
            alt.Chart(peak_days)
            .mark_point(
                stroke=COLORS["card"],
                fill=COLORS["primary"],
                filled=True,
                size=112,
                strokeWidth=2.2,
            )
            .encode(x=shared_x, y=line_y)
        )
        hover_point = (
            alt.Chart(daily)
            .mark_point(
                stroke=COLORS["primary"],
                fill=COLORS["card"],
                filled=True,
                size=86,
                strokeWidth=2.4,
            )
            .encode(
                x=shared_x,
                y=line_y,
                opacity=alt.condition(hover, alt.value(1), alt.value(0), empty=False),
            )
        )
        hover_rule = (
            alt.Chart(daily)
            .mark_rule(color=COLORS["primary"], strokeWidth=1, strokeDash=[3, 4])
            .encode(
                x=shared_x,
                opacity=alt.condition(hover, alt.value(0.34), alt.value(0), empty=False),
            )
        )
        selector = (
            alt.Chart(daily)
            .mark_rule(opacity=0.001, strokeWidth=max(22, bar_size + 12))
            .encode(
                x=shared_x,
                tooltip=[
                    alt.Tooltip("完整日期:N", title="日期"),
                    alt.Tooltip("风险总量:Q", title="总风险", format="d"),
                    alt.Tooltip("高风险明细:N", title="高风险"),
                    alt.Tooltip("中风险明细:N", title="中风险"),
                    alt.Tooltip("低风险明细:N", title="低风险"),
                ],
            )
            .add_params(hover)
        )
        trend_chart = (
            alt.layer(
                axis_carrier,
                divider,
                bars,
                line,
                nonzero_points,
                peak_points,
                top_band_label,
                lower_band_label,
                hover_rule,
                hover_point,
                selector,
            )
            .properties(height=340)
            .configure_axis(labelFont="Segoe UI", titleFont="Segoe UI")
            .configure_view(fill=COLORS["card"], strokeWidth=0)
        )
        st.altair_chart(trend_chart, use_container_width=True)


def _render_filters(st) -> tuple[date, date, str, bool, str, str, str, str]:
    today = date.today()
    with st.container(key="chat_filter_panel"):
        st.markdown(
            """
            <div class="chat-filter-head">
                <div>
                    <div class="chat-filter-title">风险检索台</div>
                    <div class="chat-filter-caption">时间窗口常驻，低频条件收进抽屉；趋势与记录始终使用同一组条件。</div>
                </div>
                <span class="chat-filter-mode">实时联动</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.container(key="chat_filter_command_bar"):
            st.session_state.setdefault("chat_date_quick_range", "今天")
            range_col, keyword_col, merge_col = st.columns([1.45, 2.35, 1.05])
            quick_range = range_col.segmented_control(
                "日期范围",
                options=("今天", "近7天", "近30天", "自定义"),
                key="chat_date_quick_range",
            )
            keyword = keyword_col.text_input(
                "用户/关键词搜索",
                value="",
                placeholder="输入用户、关键词或消息片段",
            )
            merge_duplicates = merge_col.toggle(
                "合并疑似重复记录",
                key="chat_merge_duplicates",
            )

            if quick_range == "今天":
                start_date = today
                end_date = today
            elif quick_range == "近7天":
                start_date = today - timedelta(days=6)
                end_date = today
            elif quick_range == "近30天":
                start_date = today - timedelta(days=29)
                end_date = today
            else:
                date_left, date_right = st.columns(2)
                st.session_state.setdefault("chat_start_date", today)
                st.session_state.setdefault("chat_end_date", today)
                start_date = date_left.date_input("开始日期", key="chat_start_date")
                end_date = date_right.date_input("结束日期", key="chat_end_date")

            with st.container(key="chat_filter_drawer"):
                with st.expander("更多条件 · 频道 / 风险等级 / 风险类型 / 处理状态", expanded=False):
                    channel_col, level_col, type_col, status_col = st.columns(4)
                    channel_name = channel_col.selectbox("频道", CHANNEL_OPTIONS, index=0)
                    risk_level = level_col.selectbox("风险等级", RISK_LEVELS, index=0)
                    risk_type = type_col.selectbox("风险类型", RISK_TYPES, index=0)
                    status = status_col.selectbox("处理状态", STATUS_OPTIONS, index=0)
    return start_date, end_date, keyword, merge_duplicates, channel_name, risk_level, risk_type, status


def _filter_records(
    records: list[dict],
    keyword: str,
    channel_name: str,
    risk_level: str,
    risk_type: str,
    status: str,
) -> list[dict]:
    output = records
    if keyword.strip():
        needle = keyword.strip().lower()
        output = [
            record
            for record in output
            if needle in " ".join(str(value).lower() for value in record.values())
        ]
    if channel_name != "全部":
        output = [record for record in output if record.get("channel_name") == channel_name]
    if risk_level != "全部":
        output = [record for record in output if record.get("risk_level") == risk_level]
    if risk_type != "全部":
        output = [record for record in output if record.get("risk_type") == risk_type]
    if status != "全部":
        output = [record for record in output if record.get("status") == status]
    return output


def _table_records(records: list[dict]) -> list[dict]:
    return [
        {
            "ID": record.get("id"),
            "时间": _compact_datetime(record.get("created_time")),
            "频道": f"#{record.get('channel_name') or MONITORED_CHANNELS[0]}",
            "风险等级": record.get("risk_level"),
            "用户": record.get("discord_user_id") or "未知用户",
            "内容摘要": _short_text(record.get("message")),
            "风险类型": record.get("risk_type"),
            "AI置信度": f"{float(record.get('confidence') or 0):.0%}",
            "处理状态": record.get("status"),
            "操作": "选择记录查看详情",
        }
        for record in records
    ]


def _risk_selector_label(record: dict) -> str:
    return (
        f"#{record.get('id')} · {_compact_datetime(record.get('created_time'))} · "
        f"{record.get('risk_level') or '低风险'} · #{record.get('channel_name') or MONITORED_CHANNELS[0]} · "
        f"{_short_text(record.get('message'), 52)}"
    )


def _render_member_moderation_dialog(st, record: dict, author_name: str) -> None:
    record_id = int(record.get("id") or 0)
    guild_id = str(record.get("guild_id") or "").strip()
    discord_user_id = str(record.get("discord_user_id") or "").strip()
    result_key = f"chat_moderation_result_{record_id}"

    @st.dialog("Discord 成员管理", width="large")
    def moderation_dialog() -> None:
        st.markdown(
            f"<div class='chat-moderation-head'><div><div class='chat-moderation-title'>管理风险记录 #{record_id} 的成员</div>"
            f"<div class='chat-filter-caption'>由 Bot 执行，处理原因会写入 Discord 审核日志。</div></div>"
            f"<div class='chat-moderation-meta'>目标成员<br><strong>{escape(author_name)}</strong></div></div>",
            unsafe_allow_html=True,
        )
        if not guild_id or not discord_user_id:
            st.error("当前风险记录缺少服务器或用户信息，无法执行 Discord 成员管理。")
        else:
            with st.form(f"chat_moderation_form_{record_id}", border=False):
                action_col, duration_col = st.columns(2)
                action = action_col.selectbox(
                    "管理动作",
                    options=(ACTION_TIMEOUT, ACTION_KICK, ACTION_BAN),
                    format_func=lambda value: ACTION_LABELS[value],
                )
                timeout_label = duration_col.selectbox(
                    "禁言时长（仅禁言时生效）",
                    options=tuple(TIMEOUT_OPTIONS),
                )
                reason = st.text_area(
                    "处理原因",
                    height=88,
                    max_chars=400,
                    placeholder="说明触发该管理动作的原因，将同步写入 Discord 审核日志…",
                )
                st.warning("封禁和踢出会立即影响玩家访问服务器；Bot 还必须具备对应权限且角色高于目标成员。")
                confirmed = st.checkbox(
                    f"我确认要对 {author_name} 执行所选操作，并已核对处理原因。"
                )
                cancel_col, submit_col = st.columns(2)
                cancelled = cancel_col.form_submit_button("取消", use_container_width=True)
                submitted = submit_col.form_submit_button(
                    "确认执行", type="primary", use_container_width=True
                )

            if cancelled:
                st.rerun()

            if submitted:
                if not reason.strip():
                    st.error("请填写处理原因；该内容会同步写入 Discord 审核日志。")
                elif not confirmed:
                    st.error("请先勾选确认项，成员管理操作尚未执行。")
                else:
                    audit_reason = f"AIDC 风险记录 #{record_id}: {reason.strip()}"
                    timeout_minutes = TIMEOUT_OPTIONS[timeout_label] if action == ACTION_TIMEOUT else None
                    try:
                        with st.spinner("正在通过 Discord Bot 执行成员管理…"):
                            result = MemberModerationService().moderate(
                                guild_id,
                                discord_user_id,
                                action,
                                audit_reason,
                                timeout_minutes,
                            )
                    except (RuntimeError, ValueError) as exc:
                        st.error(str(exc))
                    else:
                        message = f"已通过 Discord Bot 对 {author_name} 执行：{result.action_label}。"
                        if result.timeout_until:
                            message += f" 禁言截止时间：{result.timeout_until.astimezone().strftime('%Y/%m/%d %H:%M')}。"
                        st.session_state[result_key] = message
                        st.rerun()

    moderation_dialog()


def _render_detail_panel(st, db_path, record: dict | None, all_records: list[dict]) -> None:
    if record is None:
        st.markdown(
            """
                <div class="chat-detail-panel">
                    <div class="chat-detail-title">风险详情</div>
                    <div class="chat-detail-meta">从上方记录抽屉选择一条风险记录后，查看原始消息、AI 判断和处理入口。</div>
                    <div class="chat-detail-message">暂无选中记录</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    same_user_count = sum(1 for item in all_records if item.get("discord_user_id") == record.get("discord_user_id"))
    discord_url = (
        f"https://discord.com/channels/@me/{record.get('channel_id')}/{record.get('discord_message_id')}"
        if record.get("channel_id") and record.get("discord_message_id")
        else ""
    )
    risk_level = str(record.get("risk_level") or "低风险")
    risk_class = {
        "高风险": "high",
        "中风险": "medium",
        "低风险": "low",
    }.get(risk_level, "low")
    status = str(record.get("status") or "待处理")
    status_class = {
        "待处理": "pending",
        "已处理": "resolved",
        "已忽略": "ignored",
    }.get(status, "pending")
    names_by_id = _resolved_record_identities(st, db_path, record)
    author_id = str(record.get("discord_user_id") or "").strip()
    author_name = names_by_id.get(author_id) or "未知用户"
    display_message = _replace_discord_mentions(record.get("message"), names_by_id)
    moderation_result_key = f"chat_moderation_result_{record.get('id')}"
    moderation_result = st.session_state.pop(moderation_result_key, None)
    if moderation_result:
        st.success(str(moderation_result))
    st.markdown(
        f"""
        <div class="chat-detail-panel">
            <div class="chat-detail-heading">
                <div>
                    <div class="chat-detail-eyebrow">风险详情</div>
                    <div class="chat-detail-title">记录 #{escape(str(record.get("id") or "-"))}</div>
                </div>
                <span class="chat-status-chip {status_class}">{escape(status)}</span>
            </div>
            <div class="chat-detail-meta-row">
                <span>{escape(_compact_datetime(record.get("created_time")))}</span>
                <span>#{escape(str(record.get("channel_name") or MONITORED_CHANNELS[0]))}</span>
                <span class="chat-risk-chip {risk_class}">{escape(risk_level)}</span>
            </div>
            <div class="chat-detail-message">
                <span>原始消息</span>
                {escape(display_message)}
            </div>
            <div class="chat-detail-grid">
                <div class="chat-detail-cell user-id"><span>Discord 用户</span><strong>{escape(author_name)}</strong></div>
                <div class="chat-detail-cell"><span>AI 判断理由</span><strong>{escape(str(record.get("risk_reason") or "风险表达"))}</strong></div>
                <div class="chat-detail-cell"><span>AI 置信度</span><strong>{float(record.get("confidence") or 0):.0%}</strong></div>
                <div class="chat-detail-cell"><span>近期风险次数</span><strong>{same_user_count}</strong></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="chat_detail_actions"):
        st.caption("处理操作")
        primary_actions = st.columns(2)
        if primary_actions[0].button(
            "标记已处理",
            type="primary",
            use_container_width=True,
            key=f"resolve_risk_{record.get('id')}",
        ):
            _set_risk_status(record.get("id"), "已处理")
            st.rerun()
        if primary_actions[1].button(
            "成员管理",
            use_container_width=True,
            key=f"moderate_risk_{record.get('id')}",
        ):
            _render_member_moderation_dialog(st, record, author_name)

        secondary_actions = st.columns(2)
        if secondary_actions[0].button(
            "忽略",
            use_container_width=True,
            key=f"ignore_risk_{record.get('id')}",
        ):
            _set_risk_status(record.get("id"), "已忽略")
            st.rerun()
        if discord_url:
            secondary_actions[1].link_button("打开 Discord", discord_url, use_container_width=True)
        else:
            secondary_actions[1].button("打开 Discord", disabled=True, use_container_width=True)


def _render_records_workspace(st, db_path, data: list[dict]) -> None:
    with st.container(key="chat_records_workspace", border=True):
        action_cols = st.columns(3)
        if action_cols[0].button("查询", use_container_width=True, key="chat_records_query"):
            st.rerun()
        action_cols[1].button(
            "重置",
            use_container_width=True,
            on_click=_reset_chat_filters,
            key="chat_records_reset",
        )
        action_cols[2].download_button(
            "导出 CSV",
            data=records_to_csv(_table_records(data)),
            file_name="chat_risk_monitor.csv",
            mime="text/csv",
            use_container_width=True,
        )

        if not data:
            st.markdown(
                '<div class="empty-state">当前筛选条件下暂无聊天风险记录。可以扩大日期范围或清空关键词后再查询。</div>',
                unsafe_allow_html=True,
            )
            return

        record_by_id = {int(record["id"]): record for record in data}
        option_ids = tuple(record_by_id)
        selected_key = "chat_selected_risk_id"
        if st.session_state.get(selected_key) not in option_ids:
            st.session_state[selected_key] = option_ids[0]
        selected_before_open = record_by_id[int(st.session_state[selected_key])]
        drawer_label = (
            f"选择风险记录 · 当前 #{selected_before_open.get('id')} · "
            f"共 {len(data)} 条"
        )
        with st.container(key="chat_risk_drawer"):
            with st.expander(drawer_label, expanded=False):
                selected_id = st.selectbox(
                    "风险记录",
                    options=option_ids,
                    format_func=lambda value: _risk_selector_label(record_by_id[int(value)]),
                    key=selected_key,
                    help="支持输入记录编号、频道或消息关键词快速定位。",
                )
                selected_preview = record_by_id[int(selected_id)]
                st.markdown(
                    f"<div class='chat-selection-note'><span>选中后，下方只展示这一条记录的完整详情。</span>"
                    f"<strong>{escape(str(selected_preview.get('status') or '待处理'))}</strong></div>",
                    unsafe_allow_html=True,
                )

        selected_record = record_by_id.get(int(st.session_state[selected_key]))
        _render_detail_panel(st, db_path, selected_record, data)


def render(st, db_path) -> None:
    _render_chat_monitor_css(st)
    today = date.today()
    st.session_state.setdefault("chat_start_date", today)
    st.session_state.setdefault("chat_end_date", today)
    st.session_state.setdefault("chat_merge_duplicates", True)

    header_left, header_right = st.columns([4, 1])
    header_left.markdown(
        f"""
        <div class="chat-section-head">
            <div>
                <div class="chat-section-title">风险概览</div>
                <div class="chat-section-caption">监控 {MONITORED_CHANNELS_LABEL} 中需要关注的风险言论。</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if header_right.button("日历视图", use_container_width=True):
        st.session_state["chat_calendar_open"] = True
    if st.session_state.get("chat_calendar_open"):
        _render_calendar_dialog(st, db_path)

    max_start = today - timedelta(days=29)
    all_start_time, all_end_time = date_range_to_datetimes(max_start, today)
    all_rows = _cached_channel_messages(st, db_path, all_start_time, all_end_time, 10000)
    all_risks = _risk_records(all_rows)
    merge_duplicates = bool(st.session_state.get("chat_merge_duplicates", True))
    overview_risks = _dedupe_nearby_duplicates(all_risks) if merge_duplicates else all_risks
    today_risks = [
        record
        for record in overview_risks
        if (_parse_created_time(record.get("created_time")) or datetime.min).date() == today
    ]
    yesterday = today - timedelta(days=1)
    yesterday_risks = [
        record
        for record in overview_risks
        if (_parse_created_time(record.get("created_time")) or datetime.min).date() == yesterday
    ]
    week_risks = [
        record
        for record in overview_risks
        if (_parse_created_time(record.get("created_time")) or datetime.min).date() >= today - timedelta(days=6)
    ]
    high_pending_count = sum(
        1
        for record in overview_risks
        if record.get("risk_level") == "高风险" and record.get("status") == "待处理"
    )
    pending_count = sum(1 for record in overview_risks if record.get("status") == "待处理")
    _render_overview(
        st,
        len(today_risks),
        len(yesterday_risks),
        len(week_risks),
        high_pending_count,
        pending_count,
        merge_duplicates,
    )

    trend_slot = st.empty()
    start_date, end_date, keyword, merge_duplicates, channel_name, risk_level, risk_type, status = _render_filters(st)
    if start_date > end_date:
        st.warning("开始日期不能晚于结束日期。")
        return

    start_time, end_time = date_range_to_datetimes(start_date, end_date)
    rows = _cached_channel_messages(st, db_path, start_time, end_time, 10000)
    data = _risk_records(rows)
    removed_count = 0
    if merge_duplicates:
        original_count = len(data)
        data = _dedupe_nearby_duplicates(data)
        removed_count = original_count - len(data)

    data = _filter_records(data, keyword, channel_name, risk_level, risk_type, status)
    period_days = (end_date - start_date).days + 1
    previous_end_date = start_date - timedelta(days=1)
    previous_start_date = previous_end_date - timedelta(days=period_days - 1)
    previous_start_time, previous_end_time = date_range_to_datetimes(previous_start_date, previous_end_date)
    previous_rows = _cached_channel_messages(st, db_path, previous_start_time, previous_end_time, 10000)
    previous_data = _risk_records(previous_rows)
    if merge_duplicates:
        previous_data = _dedupe_nearby_duplicates(previous_data)
    previous_data = _filter_records(
        previous_data,
        keyword,
        channel_name,
        risk_level,
        risk_type,
        status,
    )
    filtered_pending_count = sum(1 for record in data if record.get("status") == "待处理")
    filtered_resolved_count = sum(1 for record in data if record.get("status") == "已处理")

    with trend_slot.container():
        with st.container(key="chat_trend_workspace"):
            trend_col, focus_col = st.columns([0.7, 0.3])
            with trend_col:
                _render_trend(st, start_date, end_date, data, previous_total=len(previous_data))
            with focus_col:
                _render_focus_card(st, db_path, data, start_date, end_date)

    with st.container(key="chat_result_panel"):
        if removed_count > 0:
            st.caption(f"已隐藏 {removed_count} 条几秒内重复写入的疑似重复记录。")
        st.markdown(
            f"""
            <div class="chat-section-head">
                <div>
                    <div class="chat-section-title">风险记录</div>
                    <div class="chat-section-caption">当前筛选 {len(data)} 条 · 待处理 {filtered_pending_count} 条 · 已处理 {filtered_resolved_count} 条</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _render_records_workspace(st, db_path, data)
