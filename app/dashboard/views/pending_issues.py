from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from html import escape

import pandas as pd

from app.dashboard.export_utils import records_to_csv
from app.dashboard.formatters import date_range_to_datetimes, rows_to_records
from app.dashboard.ticket_reply_service import TicketReplyService
from app.database.repositories.pending_ticket_repository import PendingTicketRepository


TICKET_STATUSES = ("Open", "In Progress", "Answered", "Closed", "Ignored")
AI_DM_UNRESOLVED_SOURCE = "AI_DM_UNRESOLVED"
PENDING_CACHE_REVISION_KEY = "_pending_issues_cache_revision"
TICKET_STATUS_LABELS = {
    "All": "全部",
    "Open": "待答",
    "In Progress": "处理中",
    "Answered": "已回复",
    "Closed": "已关闭",
    "Ignored": "忽略",
}


def _pending_cache_revision(st) -> int:
    return int(st.session_state.setdefault(PENDING_CACHE_REVISION_KEY, 0))


def _clear_pending_caches(st) -> None:
    st.session_state[PENDING_CACHE_REVISION_KEY] = _pending_cache_revision(st) + 1

def _cached_open_counts(st, db_path, month_start: str, status_end: str) -> dict[str, int]:
    @st.cache_data(ttl=20, show_spinner=False)
    def _load(path: str, start: str, end: str, cache_revision: int) -> dict[str, int]:
        return PendingTicketRepository(path).count_open_by_date_between(
            start,
            end,
            ticket_source=AI_DM_UNRESOLVED_SOURCE,
        )

    return _load(str(db_path), month_start, status_end, _pending_cache_revision(st))


def _cached_ticket_rows(st, db_path, start_time, end_time, status_filter: str) -> list[dict]:
    @st.cache_data(ttl=20, show_spinner=False)
    def _load(path: str, start_value, end_value, selected_status: str, cache_revision: int) -> list[dict]:
        rows = PendingTicketRepository(path).list_ai_dm_unresolved_filtered(
            start_value,
            end_value,
            selected_status,
        )
        return rows_to_records(rows)

    return _load(str(db_path), start_time, end_time, status_filter, _pending_cache_revision(st))


def _extract_resolution_ids(records: list[dict]) -> list[int]:
    return [
        int(record["id"])
        for record in records
        if record.get("标记已解决") and record.get("status") != "Closed"
    ]


def _format_ticket_records(records: list[dict]) -> list[dict]:
    formatted = []
    for record in records:
        row = dict(record)
        channel_name = row.pop("channel_display_name", None) or "未知频道 / 私信"
        channel_id = row.pop("channel_id", None)
        if channel_name == "未知频道 / 私信" and channel_id:
            row["频道/私信"] = f"{channel_name} ({channel_id})"
        else:
            row["频道/私信"] = f"#{channel_name}" if channel_name != "私信" else channel_name
        formatted.append(row)
    return formatted


def _month_bounds(target_date: date) -> tuple[date, date]:
    last_day = calendar.monthrange(target_date.year, target_date.month)[1]
    return date(target_date.year, target_date.month, 1), date(target_date.year, target_date.month, last_day)


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if " " in text else text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _is_open_status(status: object) -> bool:
    return str(status or "") in {"Open", "In Progress"}


def _is_overdue(record: dict, today: date) -> bool:
    created_date = _parse_date(record.get("created_time"))
    return _is_open_status(record.get("status")) and created_date is not None and (today - created_date).days >= 2


def _ticket_day_stats(records: list[dict], start_day: date, days: int, today: date) -> list[dict]:
    stats = []
    for offset in range(days):
        target = start_day + timedelta(days=offset)
        day_records = [record for record in records if _parse_date(record.get("created_time")) == target]
        open_records = [record for record in day_records if _is_open_status(record.get("status"))]
        closed_records = [record for record in day_records if str(record.get("status") or "") == "Closed"]
        overdue_records = [record for record in day_records if _is_overdue(record, today)]
        stats.append(
            {
                "date": target,
                "new": len(day_records),
                "open": len(open_records),
                "closed": len(closed_records),
                "overdue": len(overdue_records),
                "high": len(overdue_records),
            }
        )
    return stats


def _format_day_label(target: date) -> str:
    return f"{target.month}/{target.day}"


def _render_pending_css(st) -> None:
    st.markdown(
        """
        <style>
        .pending-load-wrap {
            margin: 2px 0 14px;
        }
        .pending-load-head {
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:16px;
            margin-bottom:10px;
        }
        .pending-load-title {
            font-size:18px;
            font-weight:650;
            color:#1D1D1F;
        }
        .pending-load-caption {
            margin-top:2px;
            font-size:13px;
            color:#6E6E73;
        }
        .pending-metrics {
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:12px;
            margin:8px 0 12px;
        }
        .pending-metric {
            min-height:72px;
            padding:14px 16px;
            border:1px solid #E6EAF0;
            border-radius:14px;
            background:#fff;
        }
        .pending-metric-label {
            font-size:12px;
            color:#6E6E73;
            margin-bottom:6px;
        }
        .pending-metric-value {
            font-size:24px;
            line-height:28px;
            font-weight:650;
            color:#1D1D1F;
        }
        .pending-metric-help {
            margin-top:4px;
            font-size:12px;
            color:#8A94A3;
        }
        .pending-metric.danger .pending-metric-value,
        .pending-metric.danger .pending-metric-help {
            color:#EF4444;
        }
        .pending-load-grid {
            display:grid;
            grid-template-columns:repeat(14,minmax(58px,1fr));
            gap:8px;
            max-height:84px;
        }
        .pending-day {
            min-height:64px;
            padding:8px;
            border:1px solid #E6EAF0;
            border-radius:14px;
            background:#fff;
            color:#1D1D1F;
        }
        .pending-day.today {
            border-color:#2563EB;
        }
        .pending-day.selected {
            background:#EEF5FF;
        }
        .pending-day-date {
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:6px;
            font-size:12px;
            color:#6E6E73;
        }
        .pending-day-main {
            margin-top:6px;
            font-size:12px;
            color:#1D1D1F;
            white-space:nowrap;
        }
        .pending-badges {
            margin-top:5px;
            display:flex;
            flex-wrap:wrap;
            gap:4px;
        }
        .pending-badge {
            min-width:18px;
            height:18px;
            padding:0 6px;
            border-radius:999px;
            font-size:11px;
            line-height:18px;
            font-weight:650;
            color:#fff;
        }
        .pending-badge.warn { background:#F59E0B; }
        .pending-badge.danger { background:#EF4444; }
        .pending-done {
            color:#22C55E;
            font-size:15px;
            font-weight:750;
        }
        .pending-zero {
            min-height:88px;
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:16px;
            padding:18px 20px;
            border:1px solid #BDECCF;
            border-radius:14px;
            background:#F0FDF4;
            color:#166534;
        }
        .pending-zero strong {
            display:block;
            color:#14532D;
            font-size:15px;
            margin-bottom:4px;
        }
        .pending-current-filter {
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:12px;
            padding:10px 14px;
            margin:8px 0 14px;
            border:1px solid #E6EAF0;
            border-radius:12px;
            background:#F8FAFC;
            color:#4B5563;
            font-size:13px;
        }
        .issue-calendar-title {
            display:flex;
            align-items:center;
            justify-content:center;
            gap:12px;
            margin:2px 0 12px;
            color:#1D1D1F;
            font-weight:650;
        }
        .issue-calendar {
            display:grid;
            grid-template-columns:repeat(7,minmax(74px,1fr));
            gap:8px;
        }
        .issue-calendar-weekday {
            color:#8A94A3;
            font-size:12px;
            text-align:center;
        }
        .issue-calendar-day {
            min-height:70px;
            border:1px solid #E6EAF0;
            border-radius:14px;
            background:#fff;
            padding:8px;
        }
        .issue-calendar-day.today {
            border-color:#2563EB;
        }
        .issue-calendar-day.empty {
            border-color:transparent;
            background:transparent;
        }
        .issue-calendar-number {
            font-size:13px;
            color:#1D1D1F;
            font-weight:600;
        }
        .issue-calendar-meta {
            margin-top:5px;
            display:flex;
            flex-wrap:wrap;
            gap:4px;
        }
        .pending-load-title,
        .pending-metric-value,
        .pending-day-main,
        .issue-calendar-title,
        .issue-calendar-number { color: var(--text-primary); }
        .pending-load-caption,
        .pending-metric-label,
        .pending-current-filter,
        .pending-day-date,
        .issue-calendar-weekday { color: var(--text-secondary); }
        .pending-metric-help { color: var(--text-tertiary); }
        .pending-metrics { grid-template-columns: repeat(auto-fit, minmax(168px, 1fr)); gap: 12px; margin: 8px 0 16px; }
        .pending-metric,
        .pending-day,
        .issue-calendar-day { background: var(--surface); border-color: var(--border); border-radius: var(--radius-card); }
        .pending-metric { min-height: 84px; padding: 14px 16px; }
        .pending-metric.danger .pending-metric-value,
        .pending-metric.danger .pending-metric-help { color: var(--danger); }
        .pending-day.today,
        .issue-calendar-day.today { border-color: var(--primary); }
        .pending-day.selected { background: var(--primary-soft); }
        .pending-badge.warn { background: var(--warning); }
        .pending-badge.danger { background: var(--danger); }
        .pending-done { color: var(--success); }
        .pending-zero { background: var(--success-soft); border-color: color-mix(in srgb, var(--success) 24%, var(--border)); color: var(--success); border-radius: var(--radius-card); }
        .pending-zero strong { color: var(--success); }
        .pending-current-filter { background: var(--surface-muted); border-color: var(--border); border-radius: var(--radius-control); }
        @media (max-width: 980px) {
            .pending-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .pending-load-grid { grid-template-columns:repeat(7,minmax(58px,1fr)); max-height:none; }
        }
        @media (max-width: 560px) {
            .pending-metrics { grid-template-columns:1fr 1fr; gap:8px; }
            .pending-metric { min-height:80px; padding:12px; }
            .pending-load-head,.pending-zero,.pending-current-filter { align-items:flex-start; flex-direction:column; }
            .pending-load-grid { grid-template-columns:repeat(4,minmax(58px,1fr)); }
            .issue-calendar { grid-template-columns:repeat(7,minmax(36px,1fr)); gap:4px; }
            .issue-calendar-day { min-height:54px; padding:5px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _date_marker(target_date: date, today: date, open_counts: dict[str, int]) -> str | None:
    if target_date > today:
        return None
    return "red" if open_counts.get(target_date.isoformat(), 0) > 0 else "green"


def _build_issue_calendar_html(target_month: date, today: date, day_stats: dict[str, dict] | dict[str, int]) -> str:
    month_start, _ = _month_bounds(target_month)
    first_weekday, month_days = calendar.monthrange(month_start.year, month_start.month)
    cells: list[date | None] = [None] * first_weekday
    cells.extend(date(month_start.year, month_start.month, day) for day in range(1, month_days + 1))
    while len(cells) % 7:
        cells.append(None)

    weekday_cells = "".join(f"<div class='issue-calendar-weekday'>{label}</div>" for label in ("一", "二", "三", "四", "五", "六", "日"))
    day_cells = []
    for cell_date in cells:
        if cell_date is None:
            day_cells.append("<div class='issue-calendar-day empty'></div>")
            continue

        raw_stats = day_stats.get(cell_date.isoformat(), {})
        if isinstance(raw_stats, int):
            stats = {"new": 0, "open": raw_stats, "closed": 0, "overdue": 0, "high": 0}
        else:
            stats = raw_stats
        badges = []
        if int(stats.get("overdue", 0) or 0) or int(stats.get("high", 0) or 0):
            badges.append(f"<span class='pending-badge danger' title='超时或高优先级'>{int(stats.get('overdue', 0) or stats.get('high', 0) or 0)}</span>")
        if int(stats.get("open", 0) or 0):
            badges.append(f"<span class='pending-badge warn' title='待答'>{int(stats.get('open', 0) or 0)}</span>")
        if int(stats.get("new", 0) or 0):
            badges.append(f"<span class='pending-badge warn' title='新增'>+{int(stats.get('new', 0) or 0)}</span>")
        if int(stats.get("closed", 0) or 0) and not int(stats.get("open", 0) or 0):
            badges.append("<span class='pending-done' title='当天待答已完成'>✓</span>")
        today_class = " today" if cell_date == today else ""
        tooltip = (
            f"新增 {int(stats.get('new', 0) or 0)}，已完成 {int(stats.get('closed', 0) or 0)}，"
            f"待答 {int(stats.get('open', 0) or 0)}，超时 {int(stats.get('overdue', 0) or 0)}"
        )
        day_cells.append(
            f"<div class='issue-calendar-day{today_class}' title='{escape(tooltip)}'>"
            f"<div class='issue-calendar-number'>{cell_date.day}</div>"
            f"<div class='issue-calendar-meta'>{''.join(badges)}</div>"
            "</div>"
        )

    return f"""
    <div class="issue-calendar-title">{target_month.year}年{target_month.month}月</div>
    <div class="issue-calendar">
        {weekday_cells}
        {''.join(day_cells)}
    </div>
    """


def _build_load_html(day_stats: list[dict], selected_day: date | None, today: date) -> str:
    cells = []
    for stats in day_stats:
        target = stats["date"]
        classes = ["pending-day"]
        if target == today:
            classes.append("today")
        if selected_day == target:
            classes.append("selected")
        badges = []
        if stats["overdue"] or stats["high"]:
            badges.append(f"<span class='pending-badge danger' title='超时或高优先级'>{stats['overdue'] or stats['high']}</span>")
        if stats["open"]:
            badges.append(f"<span class='pending-badge warn' title='待答'>{stats['open']}</span>")
        if stats["closed"] and not stats["open"]:
            badges.append("<span class='pending-done' title='当天待答已完成'>✓</span>")
        cells.append(
            f"<div class='{' '.join(classes)}'>"
            f"<div class='pending-day-date'><span>{_format_day_label(target)}</span>{''.join(badges[:1])}</div>"
            f"<div class='pending-day-main'>新增 {stats['new']}</div>"
            f"<div class='pending-day-main'>待答 {stats['open']}</div>"
            f"<div class='pending-badges'>{''.join(badges[1:])}</div>"
            "</div>"
        )
    return f"<div class='pending-load-grid'>{''.join(cells)}</div>"


def _render_pending_metrics(st, records: list[dict], today: date, open_count: int) -> None:
    today_new = sum(1 for record in records if _parse_date(record.get("created_time")) == today)
    overdue = sum(1 for record in records if _is_overdue(record, today))
    week_start = today - timedelta(days=today.weekday())
    week_done = sum(
        1
        for record in records
        if str(record.get("status") or "") == "Closed"
        and (closed_day := _parse_date(record.get("updated_time") or record.get("created_time"))) is not None
        and week_start <= closed_day <= today
    )
    cards = [
        ("今日新增", today_new, "较昨日持平", ""),
        ("当前待答", open_count, "待答 + 处理中", ""),
        ("已超时", overdue, "超过 48 小时未关闭", "danger" if overdue else ""),
        ("本周已完成", week_done, "本周关闭问题", ""),
    ]
    html = "<div class='pending-metrics'>"
    for label, value, helper, tone in cards:
        html += (
            f"<div class='pending-metric {tone}'>"
            f"<div class='pending-metric-label'>{escape(label)}</div>"
            f"<div class='pending-metric-value'>{value}</div>"
            f"<div class='pending-metric-help'>{escape(helper)}</div>"
            "</div>"
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _render_issue_load(st, db_path, repository: PendingTicketRepository) -> None:
    today = date.today()
    st.session_state.setdefault("pending_load_mode", "近14天")
    st.session_state.setdefault("pending_selected_day", None)
    mode_cols = st.columns([5, 1.2])
    mode_cols[0].markdown(
        "<div class='pending-load-head'><div><div class='pending-load-title'>近14日待答负载</div>"
        "<div class='pending-load-caption'>按日期查看 FAQ 未命中问题的新增与待答压力。</div></div></div>",
        unsafe_allow_html=True,
    )
    mode = mode_cols[1].segmented_control(
        "视图",
        ["近7天", "近14天", "月历"],
        key="pending_load_mode",
        label_visibility="collapsed",
    )

    history_start = today - timedelta(days=29)
    history_start_time, history_end_time = date_range_to_datetimes(history_start, today)
    records = _cached_ticket_rows(st, db_path, history_start_time, history_end_time, "All")
    open_count = repository.count_open(ticket_source=AI_DM_UNRESOLVED_SOURCE)

    recent_records = [
        record for record in records if (created := _parse_date(record.get("created_time"))) is not None and today - timedelta(days=13) <= created <= today
    ]
    if open_count == 0 and not recent_records:
        zero_cols = st.columns([5, 1])
        zero_cols[0].markdown(
            "<div class='pending-zero'><div><strong>当前没有待答问题</strong>"
            "<span>Bot 私信与 FAQ 未命中队列已清空。</span></div></div>",
            unsafe_allow_html=True,
        )
        if zero_cols[1].button("查看历史记录", use_container_width=True):
            st.session_state["pending_start_date"] = history_start
            st.session_state["pending_end_date"] = today
        return

    _render_pending_metrics(st, records, today, open_count)

    selected_day = st.session_state.get("pending_selected_day")
    if isinstance(selected_day, str):
        selected_day = date.fromisoformat(selected_day)

    if mode == "月历":
        month_anchor = st.session_state.get("pending_calendar_month", today.replace(day=1))
        if isinstance(month_anchor, str):
            month_anchor = date.fromisoformat(month_anchor)
        nav_cols = st.columns([1, 1, 2, 1, 1])
        if nav_cols[0].button("上个月", use_container_width=True):
            previous_month = (month_anchor.replace(day=1) - timedelta(days=1)).replace(day=1)
            st.session_state["pending_calendar_month"] = previous_month
            st.rerun()
        nav_cols[2].markdown(f"<div class='issue-calendar-title'>{month_anchor.year}年{month_anchor.month}月</div>", unsafe_allow_html=True)
        if nav_cols[3].button("下个月", use_container_width=True):
            _, end_month = _month_bounds(month_anchor)
            st.session_state["pending_calendar_month"] = (end_month + timedelta(days=1)).replace(day=1)
            st.rerun()
        if nav_cols[4].button("回到今天", use_container_width=True):
            st.session_state["pending_calendar_month"] = today.replace(day=1)
            st.session_state["pending_selected_day"] = today.isoformat()
            st.session_state["pending_start_date"] = today
            st.session_state["pending_end_date"] = today
            st.rerun()
        month_start, month_end = _month_bounds(month_anchor)
        month_start_time, month_end_time = date_range_to_datetimes(month_start, month_end)
        month_records = _cached_ticket_rows(st, db_path, month_start_time, month_end_time, "All")
        month_stats = {
            item["date"].isoformat(): item
            for item in _ticket_day_stats(month_records, month_start, (month_end - month_start).days + 1, today)
        }
        st.markdown(_build_issue_calendar_html(month_anchor, today, month_stats), unsafe_allow_html=True)
    else:
        days = 7 if mode == "近7天" else 14
        start_day = today - timedelta(days=days - 1)
        day_stats = _ticket_day_stats(records, start_day, days, today)
        st.markdown(_build_load_html(day_stats, selected_day, today), unsafe_allow_html=True)

    with st.container():
        click_cols = st.columns(7 if mode == "近7天" else 14 if mode != "月历" else 7)
        if mode != "月历":
            for index, stats in enumerate(day_stats):
                if click_cols[index].button("筛选", key=f"pending_day_{stats['date'].isoformat()}", use_container_width=True):
                    st.session_state["pending_selected_day"] = stats["date"].isoformat()
                    st.session_state["pending_start_date"] = stats["date"]
                    st.session_state["pending_end_date"] = stats["date"]
                    st.rerun()
    current_day = st.session_state.get("pending_selected_day")
    if current_day:
        if isinstance(current_day, str):
            current_day_text = current_day.replace("-", "/")
        else:
            current_day_text = current_day.isoformat().replace("-", "/")
        filter_cols = st.columns([5, 1])
        filter_cols[0].markdown(
            f"<div class='pending-current-filter'>当前查看：{current_day_text} 的待答问题</div>",
            unsafe_allow_html=True,
        )
        if filter_cols[1].button("清除日期筛选", use_container_width=True):
            st.session_state["pending_selected_day"] = None
            st.session_state["pending_start_date"] = today
            st.session_state["pending_end_date"] = today
            st.rerun()


def render(st, db_path) -> None:
    _render_pending_css(st)
    repository = PendingTicketRepository(db_path)

    today = date.today()
    st.session_state.setdefault("pending_start_date", today)
    st.session_state.setdefault("pending_end_date", today)
    _render_issue_load(st, db_path, repository)

    with st.form("ticket_action_form"):
        st.subheader("待答问题与 Bot 回复")
        open_tickets = list(repository.list_open())
        ticket_options = [int(row["id"]) for row in open_tickets] or [1]
        ticket_lookup = {int(row["id"]): row for row in open_tickets}
        def ticket_label(value: int) -> str:
            row = ticket_lookup.get(value)
            if row is None:
                return f"#{value}"
            return f"#{value} · {str(row['original_message'])[:48]}"
        ticket_id = st.selectbox(
            "选择问题",
            ticket_options,
            format_func=ticket_label,
        )
        status = st.selectbox(
            "状态",
            TICKET_STATUSES,
            format_func=lambda value: TICKET_STATUS_LABELS[value],
        )
        selected_ticket = ticket_lookup.get(int(ticket_id))
        if selected_ticket is not None:
            st.caption(f"原始消息：{str(selected_ticket['original_message'])[:120]}")
        reply_content = st.text_area(
            "Bot 回复内容",
            value="",
            height=120,
            placeholder="输入需要通过 Bot 私信发送给玩家的回复内容。",
        )
        st.caption(f"字数：{len(reply_content)}")
        if reply_content.strip():
            st.markdown(
                f'<div class="reply-preview">{escape(reply_content)}</div>',
                unsafe_allow_html=True,
            )
        close_after_reply = st.checkbox("回复后关闭问题", value=False)
        left, middle, right = st.columns(3)
        update_status = left.form_submit_button("更新状态")
        send_reply = middle.form_submit_button("发送 Bot 回复")
        delete_ticket = right.form_submit_button("删除问题")

        if update_status:
            repository.update_status(int(ticket_id), status)
            _clear_pending_caches(st)
            st.success(f"问题 #{int(ticket_id)} 已更新为 {TICKET_STATUS_LABELS[status]}。")

        if send_reply:
            try:
                result = TicketReplyService(db_path).reply_to_ticket(
                    ticket_id=int(ticket_id),
                    reply=reply_content,
                    operator_name=None,
                    close_ticket=close_after_reply,
                )
            except (RuntimeError, ValueError) as exc:
                st.error(str(exc))
            else:
                _clear_pending_caches(st)
                st.success(
                    f"已通过 Bot 私信回复玩家 {result.discord_user_id}，"
                    f"问题状态：{TICKET_STATUS_LABELS[result.status]}。"
                )

        if delete_ticket:
            st.session_state["pending_delete_candidate"] = int(ticket_id)

    delete_candidate = st.session_state.get("pending_delete_candidate")
    if delete_candidate:
        confirm_cols = st.columns([5, 1, 1])
        confirm_cols[0].warning(f"确认删除问题 #{int(delete_candidate)}？删除后该问题和相关备注会一并移除。")
        if confirm_cols[1].button("确认删除", type="primary", use_container_width=True):
            repository.delete(int(delete_candidate))
            st.session_state["pending_delete_candidate"] = None
            _clear_pending_caches(st)
            st.success(f"问题 #{int(delete_candidate)} 已删除。")
            st.rerun()
        if confirm_cols[2].button("取消", use_container_width=True):
            st.session_state["pending_delete_candidate"] = None
            st.rerun()

    left, middle, right = st.columns(3)
    start_date = left.date_input("开始日期", key="pending_start_date")
    end_date = middle.date_input("结束日期", key="pending_end_date")
    status_filter = right.selectbox(
        "状态筛选",
        ("All", *TICKET_STATUSES),
        format_func=lambda value: TICKET_STATUS_LABELS[value],
    )
    start_time, end_time = date_range_to_datetimes(start_date, end_date)
    rows = _cached_ticket_rows(st, db_path, start_time, end_time, status_filter)
    data = _format_ticket_records(rows)
    if not data:
        st.markdown('<div class="empty-state">当前筛选条件下暂无待答问题。</div>', unsafe_allow_html=True)
        return

    toolbar_left, toolbar_right = st.columns([4, 1])
    toolbar_left.markdown(
        f'<div class="table-toolbar"><div class="table-toolbar-title">待答问题列表 · {len(data)} 条</div></div>',
        unsafe_allow_html=True,
    )
    toolbar_right.download_button(
        "导出 CSV",
        data=records_to_csv(data),
        file_name="pending_issues.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.caption("勾选“标记已解决”后点击下方按钮，可直接关闭已经在 Discord 或线下处理完的问题。")
    table_data = pd.DataFrame(
        [
            {
                "标记已解决": row["status"] == "Closed",
                **row,
            }
            for row in data
        ]
    )
    edited_table = st.data_editor(
        table_data,
        hide_index=True,
        use_container_width=True,
        height=460,
        disabled=[
            column
            for column in table_data.columns
            if column != "标记已解决"
        ],
        column_config={
            "标记已解决": st.column_config.CheckboxColumn(
                "标记已解决",
                help="勾选后点击按钮，将该问题状态更新为已关闭。",
            )
        },
    )
    if st.button("关闭勾选问题", type="primary"):
        selected_ids = _extract_resolution_ids(edited_table.to_dict("records"))
        if not selected_ids:
            st.info("请先在表格中勾选需要关闭的问题。")
        else:
            for ticket_id in selected_ids:
                repository.mark_resolved(ticket_id)
            _clear_pending_caches(st)
            st.success(f"已关闭 {len(selected_ids)} 个问题：{', '.join(map(str, selected_ids))}。")
            st.rerun()
