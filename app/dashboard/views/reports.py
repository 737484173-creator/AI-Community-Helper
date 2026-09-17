from __future__ import annotations

import base64
from datetime import date, datetime, timedelta
from html import escape
import re

import altair as alt
import pandas as pd

from app.dashboard.design_tokens import COLORS
from app.dashboard.export_utils import (
    records_to_csv,
    safe_download_filename,
    text_to_markdown_bytes,
)
from app.dashboard.formatters import date_range_to_datetimes, rows_to_records
from app.database.repositories.message_repository import MessageRepository
from app.database.repositories.report_repository import ReportRepository
from app.scheduler.report_jobs import ReportJobService
from app.utils.time_utils import parse_datetime


REPORT_TYPE_LABELS = {
    "All": "全部",
    "Daily": "日报",
    "Weekly": "周报",
    "Custom": "自定义",
}

REPORT_TYPE_NOTES = {
    "Daily": "汇总昨日社区消息、AI 回复、反馈和待处理事项。",
    "Weekly": "查看一周内的社区趋势、反馈主题和活动表现。",
    "Custom": "按自定义日期范围生成一次运营回顾。",
}

METRIC_LABELS = {
    "Messages": "消息数",
    "AI replies": "AI 回复",
    "Feedback items": "反馈数",
    "High priority feedback": "高优先级反馈",
    "New pending tickets": "新增待处理",
    "Open pending tickets": "未关闭事项",
}

SECTION_LABELS = {
    "Message Types": "消息类型",
    "Feedback Categories": "反馈分类",
    "Sentiment": "情绪分布",
    "Top Feedback": "重点反馈",
    "Event Performance": "活动表现",
    "Suggested Actions": "建议动作",
}

ACTIVITY_RANGE_DAYS = {
    "近7天": 7,
    "近30天": 30,
    "近90天": 90,
}

REPORT_ARCHIVE_PAGE_SIZE = 8
REPORT_ARCHIVE_GROUP_PAGE_SIZE = 6
REPORT_CACHE_REVISION_KEY = "_reports_cache_revision"


def _report_cache_revision(st) -> int:
    return int(st.session_state.setdefault(REPORT_CACHE_REVISION_KEY, 0))


def _clear_report_caches(st) -> None:
    st.session_state[REPORT_CACHE_REVISION_KEY] = _report_cache_revision(st) + 1


def _cached_message_activity_rows(st, db_path, start_time, end_time) -> list[dict]:
    """Cache the activity series without coupling it to unrelated DB writes."""

    @st.cache_data(ttl=20, show_spinner=False)
    def _load(path: str, start_value, end_value, cache_revision: int) -> list[dict]:
        rows = MessageRepository(path).count_channel_messages_by_day(start_value, end_value)
        return rows_to_records(rows)

    return _load(
        str(db_path),
        start_time,
        end_time,
        _report_cache_revision(st),
    )


def _cached_report_rows(st, db_path, report_type: str) -> list[dict]:
    """Keep archive navigation fast while allowing explicit report mutations to refresh it."""

    @st.cache_data(ttl=30, show_spinner=False)
    def _load(path: str, selected_type: str, cache_revision: int) -> list[dict]:
        repository_filter = None if selected_type == "All" else selected_type
        return rows_to_records(ReportRepository(path).list_recent(repository_filter, 1000))

    return _load(str(db_path), report_type, _report_cache_revision(st))


def _activity_date_range(
    range_name: str,
    today: date,
    custom_start: date | None = None,
    custom_end: date | None = None,
) -> tuple[date, date]:
    if range_name == "自定义":
        return custom_start or today, custom_end or today
    day_count = ACTIVITY_RANGE_DAYS.get(range_name, 30)
    return today - timedelta(days=day_count - 1), today


def _daily_message_activity(
    rows,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    days = pd.date_range(start=start_date, end=end_date, freq="D")
    counts = {
        str(row["message_date"]): int(row["total"])
        for row in rows
        if row["message_date"]
    }
    frame = pd.DataFrame({"日期": days})
    frame["完整日期"] = frame["日期"].dt.strftime("%Y-%m-%d")
    frame["消息数"] = frame["完整日期"].map(counts).fillna(0).astype(int)
    return frame


def _activity_tick_values(frame: pd.DataFrame, max_ticks: int = 8) -> list[datetime]:
    dates = [value.to_pydatetime() for value in frame["日期"]]
    if len(dates) <= max_ticks:
        return dates
    indexes = {
        round(index * (len(dates) - 1) / (max_ticks - 1))
        for index in range(max_ticks)
    }
    return [dates[index] for index in sorted(indexes)]


def _report_archive_page(
    records: list[dict],
    page: int,
    page_size: int = REPORT_ARCHIVE_PAGE_SIZE,
) -> tuple[list[dict], int, int]:
    page_count = max(1, (len(records) + page_size - 1) // page_size)
    safe_page = min(max(int(page), 1), page_count)
    start_index = (safe_page - 1) * page_size
    return records[start_index : start_index + page_size], page_count, safe_page


def _report_generation_css(st) -> None:
    st.markdown(
        """
        <style>
        div.stVerticalBlock.st-key-report_activity_workspace {
            gap: 14px;
            margin: 0 0 30px;
            padding: 20px 0 26px;
            border-top: 1px solid var(--border-strong);
            border-bottom: 1px solid var(--border);
            animation: content-enter var(--motion-enter) var(--ease-standard) both;
        }
        .report-activity-heading {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 20px;
        }
        .report-activity-title-row {
            display: flex;
            align-items: center;
            gap: 9px;
        }
        .report-activity-signal {
            position: relative;
            width: 9px;
            height: 9px;
            flex: 0 0 auto;
            border-radius: 50%;
            background: var(--primary);
            box-shadow: 0 0 0 5px color-mix(in srgb, var(--primary) 10%, transparent);
        }
        .report-activity-signal::after {
            position: absolute;
            inset: -5px;
            border: 1px solid color-mix(in srgb, var(--primary) 38%, transparent);
            border-radius: inherit;
            content: "";
            animation: report-signal-pulse 2.8s ease-out infinite;
        }
        .report-activity-title {
            color: var(--text-primary);
            font-size: 18px;
            font-weight: 720;
            line-height: 26px;
        }
        .report-activity-caption {
            margin-top: 3px;
            color: var(--text-secondary);
            font-size: 13px;
            line-height: 20px;
        }
        .report-activity-mode {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 9px;
            border: 1px solid color-mix(in srgb, var(--primary) 17%, var(--border));
            border-radius: var(--radius-pill);
            background: color-mix(in srgb, var(--primary-soft) 62%, var(--surface));
            color: var(--primary);
            font-size: 11px;
            font-weight: 680;
            line-height: 16px;
        }
        .report-activity-mode::before {
            width: 5px;
            height: 5px;
            border-radius: 50%;
            background: currentColor;
            content: "";
        }
        .report-activity-summary {
            display: flex;
            align-items: baseline;
            justify-content: flex-end;
            gap: 5px;
            color: var(--text-secondary);
            font-size: 12px;
            line-height: 20px;
            white-space: nowrap;
        }
        .report-activity-summary .range {
            margin-right: 5px;
            color: var(--text-tertiary);
        }
        .report-activity-summary strong {
            display: inline-block;
            margin: 0 1px;
            color: var(--primary);
            font-size: 16px;
            font-variant-numeric: tabular-nums;
            transition:
                color var(--motion-fast) var(--ease-standard),
                transform var(--motion-standard) var(--ease-standard);
        }
        div.stVerticalBlock.st-key-report_activity_workspace:hover .report-activity-summary strong {
            color: var(--primary-hover);
            transform: translateY(-1px);
        }
        div.stVerticalBlock.st-key-report_activity_controls { gap: 7px; }
        div.stVerticalBlock.st-key-report_activity_controls [data-testid="stSegmentedControl"] {
            width: fit-content;
        }
        div.stVerticalBlock.st-key-report_activity_chart {
            position: relative;
            gap: 0;
            overflow: hidden;
            padding: 13px 14px 2px;
            border: 1px solid color-mix(in srgb, var(--primary) 11%, var(--border));
            border-radius: var(--radius-card);
            background:
                radial-gradient(circle at 88% 0%, color-mix(in srgb, var(--primary-soft) 68%, transparent), transparent 34%),
                linear-gradient(180deg, color-mix(in srgb, var(--primary-soft) 22%, var(--surface)) 0%, var(--surface) 76%);
            box-shadow: 0 1px 2px rgba(16, 24, 40, .025);
            transform: translateZ(0);
            transition:
                transform var(--motion-standard) var(--ease-standard),
                border-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard),
                background-color var(--motion-standard) var(--ease-standard);
        }
        div.stVerticalBlock.st-key-report_activity_chart::before {
            position: absolute;
            top: 0;
            left: 12%;
            width: 76%;
            height: 2px;
            border-radius: 999px;
            background: linear-gradient(90deg, transparent, var(--primary), #60A5FA, transparent);
            content: "";
            opacity: .72;
            transform: scaleX(.26);
            transition:
                opacity var(--motion-fast) var(--ease-standard),
                transform 360ms var(--ease-standard);
        }
        div.stVerticalBlock.st-key-report_activity_chart:hover {
            border-color: color-mix(in srgb, var(--primary) 24%, var(--border));
            box-shadow: 0 10px 28px rgba(37, 99, 235, .09);
            transform: translateY(-2px);
        }
        div.stVerticalBlock.st-key-report_activity_chart:hover::before {
            opacity: 1;
            transform: scaleX(1);
        }
        div.stVerticalBlock.st-key-report_activity_chart .stVegaLiteChart {
            transition: filter var(--motion-standard) var(--ease-standard);
        }
        div.stVerticalBlock.st-key-report_activity_chart:hover .stVegaLiteChart {
            filter: saturate(1.06);
        }
        div.stVerticalBlock.st-key-report_activity_chart svg g.mark-line path {
            transition: filter var(--motion-standard) var(--ease-standard);
        }
        @keyframes report-signal-pulse {
            0%, 34% { opacity: .56; transform: scale(.64); }
            74%, 100% { opacity: 0; transform: scale(1.26); }
        }
        div.stVerticalBlock.st-key-report_generation_panel {
            gap: 0;
            margin: 2px 0 24px;
            border-top: 1px solid var(--border-strong);
            border-bottom: 1px solid var(--border);
            animation: content-enter var(--motion-enter) var(--ease-standard) both;
        }
        div.stVerticalBlock.st-key-report_daily_action,
        div.stVerticalBlock.st-key-report_weekly_action {
            gap: 0;
            padding: 13px 2px;
            border-bottom: 1px solid var(--border);
        }
        .report-action-label {
            color: var(--text-primary);
            font-size: 16px;
            font-weight: 680;
            line-height: 24px;
        }
        .report-action-note {
            color: var(--text-secondary);
            font-size: 13px;
            line-height: 20px;
            text-wrap: pretty;
        }
        div.stVerticalBlock.st-key-report_custom_action { gap: 0; }
        [class*="st-key-report_custom_action"] details {
            border: 0 !important;
            border-radius: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
        }
        [class*="st-key-report_custom_action"] details summary {
            min-height: 50px;
            padding: 0 2px !important;
            color: var(--text-primary);
            transition: color var(--motion-standard) var(--ease-standard);
        }
        [class*="st-key-report_custom_action"] details summary:hover { color: var(--primary); }
        [class*="st-key-report_custom_action"] details[open] summary {
            border-bottom: 1px solid var(--border);
        }
        [class*="st-key-report_custom_action"] details > div {
            padding: 14px 0 4px !important;
        }
        @media (max-width: 720px) {
            .report-activity-heading {
                align-items: flex-start;
                flex-direction: column;
                gap: 6px;
            }
            .report-activity-summary { white-space: normal; }
            div.stVerticalBlock.st-key-report_daily_action,
            div.stVerticalBlock.st-key-report_weekly_action { padding: 14px 0; }
        }
        @media (prefers-reduced-motion: reduce) {
            div.stVerticalBlock.st-key-report_activity_workspace,
            div.stVerticalBlock.st-key-report_generation_panel { animation: none !important; }
            .report-activity-signal::after,
            div.stVerticalBlock.st-key-report_activity_chart svg g.mark-line path {
                animation: none !important;
            }
            div.stVerticalBlock.st-key-report_activity_chart,
            .report-activity-summary strong { transition: none !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_message_activity_trend(st, db_path) -> None:
    today = date.today()
    st.session_state.setdefault("report_activity_range", "近30天")
    with st.container(key="report_activity_workspace"):
        st.markdown(
            """
            <div class="report-activity-heading">
                <div>
                    <div class="report-activity-title-row">
                        <span class="report-activity-signal" aria-hidden="true"></span>
                        <div class="report-activity-title">社区消息趋势</div>
                    </div>
                    <div class="report-activity-caption">每日汇总全部 Discord 频道用户发言，独立于下方日报、周报生成。</div>
                </div>
                <span class="report-activity-mode">每日更新</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.container(key="report_activity_controls"):
            range_col, summary_col = st.columns([1.15, 1.85], vertical_alignment="bottom")
            range_name = range_col.segmented_control(
                    "趋势时间范围",
                    options=("近7天", "近30天", "近90天", "自定义"),
                    key="report_activity_range",
                )
            summary_slot = summary_col.empty()
            range_name = range_name or "近30天"
            if range_name == "自定义":
                st.session_state.setdefault(
                    "report_activity_custom_start",
                    today - timedelta(days=29),
                )
                st.session_state.setdefault("report_activity_custom_end", today)
                custom_start_col, custom_end_col = st.columns(2)
                custom_start = custom_start_col.date_input(
                    "开始日期",
                    max_value=today,
                    key="report_activity_custom_start",
                )
                custom_end = custom_end_col.date_input(
                    "结束日期",
                    max_value=today,
                    key="report_activity_custom_end",
                )
            else:
                custom_start = None
                custom_end = None

        start_date, end_date = _activity_date_range(
            range_name,
            today,
            custom_start,
            custom_end,
        )
        if start_date > end_date:
            st.error("开始日期不能晚于结束日期。")
            return

        start_time, end_time = date_range_to_datetimes(start_date, end_date)
        rows = _cached_message_activity_rows(st, db_path, start_time, end_time)
        daily = _daily_message_activity(rows, start_date, end_date)
        total_messages = int(daily["消息数"].sum())
        daily_average = total_messages / max(len(daily), 1)
        summary_slot.markdown(
            f"""
            <div class="report-activity-summary">
                <span class="range">{start_date.strftime('%Y/%m/%d')}–{end_date.strftime('%Y/%m/%d')}</span>
                共<strong>{total_messages}</strong>条 · 日均<strong>{daily_average:.1f}</strong>条
            </div>
            """,
            unsafe_allow_html=True,
        )

        tick_values = _activity_tick_values(daily)
        peak_value = int(daily["消息数"].max()) if not daily.empty else 0
        peak_day = daily[daily["消息数"] == peak_value].head(1) if peak_value else daily.head(0)
        hover = alt.selection_point(
            name="report_activity_hover",
            fields=["日期"],
            nearest=True,
            on="pointerover",
            clear="pointerout",
            empty=False,
        )
        x_encoding = alt.X(
            "日期:T",
            title=None,
            axis=alt.Axis(
                format="%-m/%-d",
                labelAngle=0,
                labelColor=COLORS["text_secondary"],
                labelFontWeight=600,
                labelOverlap="greedy",
                labelPadding=10,
                values=tick_values,
                domain=False,
                ticks=False,
                grid=False,
            ),
        )
        y_encoding = alt.Y(
            "消息数:Q",
            title="消息数",
            scale=alt.Scale(zero=True, nice=True),
            axis=alt.Axis(
                tickMinStep=1,
                labelColor=COLORS["text_secondary"],
                titleColor=COLORS["text_secondary"],
                titleFontSize=11,
                titleFontWeight=600,
                titlePadding=14,
                domain=False,
                ticks=False,
                grid=True,
                gridColor="#E7EDF7",
                gridOpacity=0.78,
            ),
        )
        base = alt.Chart(daily).encode(x=x_encoding, y=y_encoding)
        area = base.mark_area(
            fill=alt.Gradient(
                gradient="linear",
                x1=1,
                x2=1,
                y1=0,
                y2=1,
                stops=[
                    alt.GradientStop(color="#4F8CFF", offset=0),
                    alt.GradientStop(color="#DBEAFE", offset=1),
                ],
            ),
            opacity=0.24,
            interpolate="monotone",
        )
        line = base.mark_line(
            color=COLORS["primary"],
            strokeWidth=3,
            strokeCap="round",
            strokeJoin="round",
            interpolate="monotone",
        )
        hover_point = base.mark_point(
            stroke=COLORS["card"],
            fill=COLORS["primary"],
            filled=True,
            size=112,
            strokeWidth=2.5,
        ).encode(
            opacity=alt.condition(hover, alt.value(1), alt.value(0), empty=False)
        )
        peak_point = (
            alt.Chart(peak_day)
            .mark_point(
                stroke=COLORS["card"],
                fill="#1D4ED8",
                filled=True,
                size=104,
                strokeWidth=2.4,
            )
            .encode(x=x_encoding, y=y_encoding)
        )
        peak_label = (
            alt.Chart(peak_day)
            .mark_text(
                color="#1D4ED8",
                dy=-15,
                font="Segoe UI",
                fontSize=11,
                fontWeight=700,
            )
            .encode(
                x=x_encoding,
                y=y_encoding,
                text=alt.Text("消息数:Q", format="d"),
            )
        )
        hover_rule = alt.Chart(daily).mark_rule(
            color=COLORS["primary"],
            strokeDash=[3, 4],
            strokeWidth=1,
        ).encode(
            x=x_encoding,
            opacity=alt.condition(hover, alt.value(0.32), alt.value(0), empty=False),
        )
        selector = alt.Chart(daily).mark_rule(opacity=0.001, strokeWidth=24).encode(
            x=x_encoding,
            tooltip=[
                alt.Tooltip("完整日期:N", title="日期"),
                alt.Tooltip("消息数:Q", title="消息数", format="d"),
            ],
        ).add_params(hover)
        chart = (
            alt.layer(area, line, peak_point, peak_label, hover_rule, hover_point, selector)
            .properties(height=270)
            .configure_axis(labelFont="Segoe UI", titleFont="Segoe UI")
            .configure_view(fill="transparent", strokeWidth=0)
        )
        with st.container(key="report_activity_chart"):
            st.altair_chart(chart, width="stretch")

def _close_report_dialog() -> None:
    st_state = __import__("streamlit").session_state
    st_state.pop("open_report_id", None)
    st_state.pop("report_edit_mode", None)
    st_state.pop("report_edit_dirty", None)


def _report_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def _report_period(content: str, fallback_start: str, fallback_end: str) -> str:
    match = re.search(r"^Period:\s*(.+)$", content, flags=re.MULTILINE)
    if match:
        return match.group(1).strip()
    return f"{fallback_start} to {fallback_end}"


def _report_display_title(report_type: str) -> str:
    if report_type == "Daily":
        return "社区运营日报"
    if report_type == "Weekly":
        return "社区运营周报"
    return "社区运营报告"


def _compact_date(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return parse_datetime(str(value)).strftime("%Y/%m/%d")
    except ValueError:
        return str(value).split(" ")[0].replace("-", "/")


def _compact_time(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return parse_datetime(str(value)).strftime("%H:%M")
    except ValueError:
        return str(value).split(" ")[-1][:5]


def _report_period_line(report: dict, content: str) -> str:
    start_value = str(report.get("start_time") or "")
    end_value = str(report.get("end_time") or "")
    created_value = str(report.get("created_time") or "")
    report_date = _compact_date(start_value or created_value)
    start_time = _compact_time(start_value)
    end_time = _compact_time(end_value)
    created_time = _compact_time(created_value)
    if report_date != "-" and start_time != "-" and end_time != "-":
        return f"{report_date} · 数据范围 {start_time}–{end_time} · 创建于{created_time}"
    period = _report_period(content, start_value or "-", end_value or "-")
    return f"{period} · 创建于{created_time}"


def _report_download_attrs(report: dict) -> tuple[str, str]:
    payload = base64.b64encode(text_to_markdown_bytes(str(report.get("content") or ""))).decode("ascii")
    filename = safe_download_filename(str(report.get("title") or "report"), "md")
    return f"data:text/markdown;base64,{payload}", filename


def _report_list_label(report: dict) -> str:
    report_type = str(report.get("report_type") or "")
    return f"{_report_display_title(report_type)} · {_compact_date(str(report.get('start_time') or report.get('created_time') or ''))}"


def _report_archive_title(report: dict) -> str:
    report_type = str(report.get("report_type") or "")
    start_date = _compact_date(str(report.get("start_time") or report.get("created_time") or ""))
    end_date = _compact_date(str(report.get("end_time") or report.get("created_time") or ""))
    if report_type == "Daily":
        return f"社区运营日报 · {start_date}"
    if report_type == "Weekly":
        return f"社区运营周报 · {start_date}–{end_date}"
    return f"自定义运营报告 · {start_date}–{end_date}"


def _report_archive_meta(report: dict, content: str) -> str:
    return (
        f"报告 #{report.get('id') or '-'} · "
        f"{_report_period_line(report, content)}"
    )


def _report_archive_date(report: dict) -> date:
    for field_name in ("start_time", "created_time", "end_time"):
        value = report.get(field_name)
        if not value:
            continue
        try:
            return parse_datetime(str(value)).date()
        except ValueError:
            continue
    return date.min


def _group_reports_by_year_month(reports: list[dict]) -> dict[int, dict[int, list[dict]]]:
    grouped: dict[int, dict[int, list[dict]]] = {}
    ordered = sorted(
        reports,
        key=lambda report: (_report_archive_date(report), int(report.get("id") or 0)),
        reverse=True,
    )
    for report in ordered:
        archive_date = _report_archive_date(report)
        grouped.setdefault(archive_date.year, {}).setdefault(archive_date.month, []).append(report)
    return grouped


def _group_reports_by_week(reports: list[dict]) -> list[tuple[date, date, list[dict]]]:
    """Group reports into Monday-Sunday archive buckets, newest first."""
    grouped: dict[date, list[dict]] = {}
    ordered = sorted(
        reports,
        key=lambda report: (_report_archive_date(report), int(report.get("id") or 0)),
        reverse=True,
    )
    for report in ordered:
        archive_date = _report_archive_date(report)
        week_start = archive_date - timedelta(days=archive_date.weekday())
        grouped.setdefault(week_start, []).append(report)
    return [
        (week_start, week_start + timedelta(days=6), grouped[week_start])
        for week_start in sorted(grouped, reverse=True)
    ]


def _report_type_summary(reports: list[dict]) -> str:
    type_counts: dict[str, int] = {}
    for report in reports:
        report_type = str(report.get("report_type") or "")
        type_counts[report_type] = type_counts.get(report_type, 0) + 1
    return " · ".join(
        f"{REPORT_TYPE_LABELS.get(report_type, report_type)} {count}"
        for report_type, count in type_counts.items()
    )


def _month_archive_label(month: int, reports: list[dict]) -> str:
    type_summary = _report_type_summary(reports)
    suffix = f" · {type_summary}" if type_summary else ""
    return f"{month:02d} 月归档 · 共 {len(reports)} 份报告{suffix}"


def _week_archive_label(week_start: date, week_end: date, reports: list[dict]) -> str:
    type_summary = _report_type_summary(reports)
    suffix = f" · {type_summary}" if type_summary else ""
    return (
        f"{week_start:%m/%d}–{week_end:%m/%d} · "
        f"第 {week_start.isocalendar().week} 周 · 共 {len(reports)} 份报告{suffix}"
    )


def _report_summary_text(content: str) -> str:
    metrics = dict(_key_metrics(content))
    pieces = [
        ("消息", metrics.get("消息数") or metrics.get("Messages")),
        ("AI回复", metrics.get("AI 回复") or metrics.get("AI replies")),
        ("反馈", metrics.get("反馈数") or metrics.get("Feedback items")),
        ("待处理", metrics.get("未关闭事项") or metrics.get("Open pending tickets")),
    ]
    return " · ".join(f"{label}{value}" for label, value in pieces if value) or "暂无摘要指标"


def _section_text(content: str, section_name: str) -> str:
    pattern = rf"^##\s+{re.escape(section_name)}\s*$([\s\S]*?)(?=^##\s+|\Z)"
    match = re.search(pattern, content, flags=re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip()


def _bullet_lines(content: str, section_name: str) -> list[str]:
    section = _section_text(content, section_name)
    lines = []
    for line in section.splitlines():
        line = line.strip()
        if line.startswith("- "):
            lines.append(line[2:].strip())
    return lines


def _key_metrics(content: str) -> list[tuple[str, str]]:
    metrics: list[tuple[str, str]] = []
    for line in _bullet_lines(content, "Key Metrics"):
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        metrics.append((METRIC_LABELS.get(label.strip(), label.strip()), value.strip()))
    return metrics


def _count_items(content: str, section_name: str) -> list[tuple[str, int]]:
    items: list[tuple[str, int]] = []
    for line in _bullet_lines(content, section_name):
        if line == "No data" or ":" not in line:
            continue
        label, value = line.rsplit(":", 1)
        try:
            count = int(value.strip())
        except ValueError:
            continue
        items.append((label.strip(), count))
    return items


def _render_count_section(title: str, items: list[tuple[str, int]]) -> str:
    if not items:
        return (
            '<div class="report-section-card">'
            f'<div class="report-section-title">{escape(title)}</div>'
            '<div class="report-preview-meta">暂无数据</div></div>'
        )
    max_count = max(count for _, count in items) or 1
    rows = []
    for label, count in items[:6]:
        width = max(4, int(count / max_count * 100))
        rows.append(
            '<div class="report-row">'
            f"<span>{escape(label)}</span><strong>{count}</strong>"
            f'<div class="report-bar"><div class="report-bar-fill" style="width:{width}%"></div></div>'
            "</div>"
        )
    return (
        '<div class="report-section-card">'
        f'<div class="report-section-title">{escape(title)}</div>'
        + "".join(rows)
        + "</div>"
    )


def _render_list_card(content: str, section_name: str) -> str:
    items = _bullet_lines(content, section_name)
    title = SECTION_LABELS.get(section_name, section_name)
    if not items or items == ["No data"]:
        body = '<div class="report-preview-meta">暂无数据</div>'
    else:
        body = (
            '<ul class="report-list">'
            + "".join(f"<li>{escape(item)}</li>" for item in items[:6])
            + "</ul>"
        )
    return (
        '<div class="report-list-card">'
        f'<div class="report-list-title">{escape(title)}</div>'
        f"{body}</div>"
    )


def _report_preview_body_html(report: dict) -> str:
    content = str(report.get("content") or "")
    metrics = _key_metrics(content)
    metric_cards = "".join(
        (
            '<div class="report-metric">'
            f'<div class="report-metric-label">{escape(label)}</div>'
            f'<div class="report-metric-value">{escape(value)}</div>'
            "</div>"
        )
        for label, value in metrics[:6]
    )
    section_cards = "".join(
        _render_count_section(SECTION_LABELS[name], _count_items(content, name))
        for name in ("Message Types", "Feedback Categories", "Sentiment")
    )
    list_cards = "".join(
        _render_list_card(content, name)
        for name in ("Top Feedback", "Event Performance", "Suggested Actions")
    )
    return (
        f'<div class="report-metric-grid">{metric_cards}</div>'
        f'<div class="report-section-grid">{section_cards}</div>'
        f"{list_cards}"
    )


def _render_report_preview(st, report: dict) -> None:
    content = str(report.get("content") or "")
    report_type = str(report.get("report_type") or "")
    title = _report_display_title(report_type)
    period_line = _report_period_line(report, content)
    download_href, download_filename = _report_download_attrs(report)
    body_html = _report_preview_body_html(report)
    st.markdown(
        f"""
        <div class="report-preview">
            <div class="report-preview-hero">
                <div>
                    <div class="report-preview-eyebrow">报告预览 · #{escape(str(report.get("id") or "-"))}</div>
                    <div class="report-preview-title-row">
                        <span class="report-type-chip">{escape(REPORT_TYPE_LABELS.get(report_type, report_type))}</span>
                        <div class="report-preview-title">{escape(title)}</div>
                    </div>
                    <div class="report-preview-meta">{escape(period_line)}</div>
                </div>
                <a class="report-export-button" href="{download_href}" download="{escape(download_filename)}">导出报告</a>
            </div>
            {body_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_report_dialog(st, report: dict) -> None:
    report_id = int(report.get("id") or 0)

    @st.dialog("报告详情", width="large")
    def report_detail_dialog() -> None:
        content = str(report.get("content") or "")
        report_type = str(report.get("report_type") or "")
        title = _report_display_title(report_type)
        period_line = _report_period_line(report, content)
        edit_key = f"report_edit_mode_{report_id}"
        draft_key = f"report_draft_{report_id}"
        unsaved_key = f"report_unsaved_{report_id}"
        st.markdown(
            f"""
            <div class="report-modal-head">
                <div>
                    <div class="report-preview-eyebrow">报告详情 · #{escape(str(report.get("id") or "-"))}</div>
                    <div class="report-preview-title-row">
                        <span class="report-type-chip">{escape(REPORT_TYPE_LABELS.get(report_type, report_type))}</span>
                        <div class="report-preview-title">{escape(title)}</div>
                    </div>
                    <div class="report-preview-meta">{escape(period_line)}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.session_state.get(edit_key, False):
            draft_value = st.text_area(
                "编辑报告草稿",
                value=st.session_state.get(draft_key, content),
                height=360,
                key=draft_key,
            )
            st.session_state[unsaved_key] = draft_value != content
            st.caption("当前为前端草稿编辑，不会修改数据库中的原始报告。")
        else:
            st.markdown(
                f'<div class="report-modal-body">{_report_preview_body_html(report)}</div>',
                unsafe_allow_html=True,
            )

        footer_cols = st.columns([1, 1, 1])
        if footer_cols[0].button("编辑报告", use_container_width=True):
            st.session_state[edit_key] = True
            st.session_state.setdefault(draft_key, content)
            st.rerun()
        footer_cols[1].download_button(
            "导出报告",
            data=text_to_markdown_bytes(content),
            file_name=safe_download_filename(str(report.get("title") or "report"), "md"),
            mime="text/markdown",
            use_container_width=True,
        )
        close_label = "关闭"
        if st.session_state.get(unsaved_key, False):
            close_label = "放弃并关闭"
            st.warning("当前有未保存的前端草稿，关闭将放弃修改。")
        if footer_cols[2].button(close_label, use_container_width=True):
            st.session_state.pop("open_report_id", None)
            st.session_state[edit_key] = False
            st.session_state[unsaved_key] = False
            st.rerun()

    report_detail_dialog()


def _render_report_archive_row(st, db_path, record: dict) -> None:
    report_id = int(record["id"])
    content = str(record.get("content") or "")
    report_type = str(record.get("report_type") or "")
    with st.container(key=f"report_archive_row_{report_id}", border=True):
        row_cols = st.columns([0.72, 3.2, 1.7, 0.7, 0.7, 0.8], vertical_alignment="center")
        row_cols[0].markdown(
            f'<span class="report-archive-type {escape(report_type.lower())}">'
            f'{escape(REPORT_TYPE_LABELS.get(report_type, report_type))}</span>',
            unsafe_allow_html=True,
        )
        row_cols[1].markdown(
            f"""
            <div class="report-archive-title">{escape(_report_archive_title(record))}</div>
            <div class="report-archive-meta">{escape(_report_archive_meta(record, content))}</div>
            """,
            unsafe_allow_html=True,
        )
        row_cols[2].markdown(
            f'<div class="report-archive-summary">{escape(_report_summary_text(content))}</div>',
            unsafe_allow_html=True,
        )
        if row_cols[3].button("查看", key=f"view_report_{report_id}", use_container_width=True):
            st.session_state["open_report_id"] = report_id
        row_cols[4].download_button(
            "导出",
            data=text_to_markdown_bytes(content),
            file_name=safe_download_filename(str(record.get("title") or "report"), "md"),
            mime="text/markdown",
            key=f"export_report_{report_id}",
            use_container_width=True,
        )
        with row_cols[5].popover("···", use_container_width=True):
            confirm_key = f"confirm_delete_report_{report_id}"
            st.caption("更多操作")
            st.checkbox("确认删除", key=confirm_key)
            if st.button(
                "删除报告",
                key=f"delete_report_{report_id}",
                disabled=not st.session_state.get(confirm_key),
            ):
                ReportRepository(db_path).delete(report_id)
                _clear_report_caches(st)
                if st.session_state.get("open_report_id") == report_id:
                    st.session_state.pop("open_report_id", None)
                st.session_state.pop(confirm_key, None)
                st.success(f"报告 #{report_id} 已删除。")
                st.rerun()


def render(st, db_path) -> None:
    _report_generation_css(st)
    _render_message_activity_trend(st, db_path)
    st.markdown(
        """
        <div class="workbench-strip">
            <div>
                <div class="workbench-title">报告生成</div>
                <div class="workbench-subtitle">选择周期后生成报告，或从历史报告中查看结构化预览。</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="report_generation_panel"):
        with st.container(key="report_daily_action"):
            daily_title, daily_note, daily_action = st.columns([0.7, 2.5, 0.8], vertical_alignment="center")
            daily_title.markdown('<div class="report-action-label">日报</div>', unsafe_allow_html=True)
            daily_note.markdown(
                f'<div class="report-action-note">{REPORT_TYPE_NOTES["Daily"]}</div>',
                unsafe_allow_html=True,
            )
            if daily_action.button("生成日报", use_container_width=True):
                result = ReportJobService(db_path).generate_daily_report()
                _clear_report_caches(st)
                st.success(f"已生成报告 #{result.report_id}。")
                st.session_state["report_type_filter"] = "Daily"
                st.session_state["open_report_id"] = int(result.report_id)
                st.rerun()

        with st.container(key="report_weekly_action"):
            weekly_title, weekly_note, weekly_action = st.columns([0.7, 2.5, 0.8], vertical_alignment="center")
            weekly_title.markdown('<div class="report-action-label">周报</div>', unsafe_allow_html=True)
            weekly_note.markdown(
                f'<div class="report-action-note">{REPORT_TYPE_NOTES["Weekly"]}</div>',
                unsafe_allow_html=True,
            )
            if weekly_action.button("生成周报", use_container_width=True):
                result = ReportJobService(db_path).generate_weekly_report()
                _clear_report_caches(st)
                st.success(f"已生成报告 #{result.report_id}。")
                st.session_state["report_type_filter"] = "Weekly"
                st.session_state["open_report_id"] = int(result.report_id)
                st.rerun()

        with st.container(key="report_custom_action"):
            with st.expander("自定义报告 · 按日期区间生成", expanded=False, key="report_custom_drawer"):
                st.caption(REPORT_TYPE_NOTES["Custom"])
                custom_start, custom_end, custom_action = st.columns([1, 1, 0.8], vertical_alignment="bottom")
                start_date = custom_start.date_input("自定义开始日期", value=date.today())
                end_date = custom_end.date_input("自定义结束日期", value=date.today())
                if custom_action.button("生成自定义报告", use_container_width=True):
                    start_time, end_time = date_range_to_datetimes(start_date, end_date)
                    try:
                        result = ReportJobService(db_path).generate_custom_report(
                            parse_datetime(start_time),
                            parse_datetime(end_time),
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        _clear_report_caches(st)
                        st.success(f"已生成报告 #{result.report_id}。")
                        st.session_state["report_type_filter"] = "Custom"
                        st.session_state["open_report_id"] = int(result.report_id)
                        st.rerun()

    st.markdown(
        """
        <div class="workbench-strip">
            <div>
                <div class="workbench-title">历史报告</div>
                <div class="workbench-subtitle">切换类型并选择报告，页面会展示更适合运营查看的结构化摘要。</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    filter_col, export_col = st.columns([3, 1])
    st.session_state.setdefault("report_type_filter", "All")
    report_type = filter_col.segmented_control(
        "报告类型",
        options=("All", "Daily", "Weekly", "Custom"),
        key="report_type_filter",
        format_func=lambda value: REPORT_TYPE_LABELS[value],
        on_change=_close_report_dialog,
    )
    report_records = [
        record
        for record in _cached_report_rows(st, db_path, report_type)
        if str(record.get("report_type") or "") in ("Daily", "Weekly", "Custom")
    ]
    if not report_records:
        st.markdown('<div class="empty-state">暂无报告。可以先生成日报、周报或自定义报告。</div>', unsafe_allow_html=True)
        return

    export_col.download_button(
        "导出报告列表 CSV",
        data=records_to_csv(report_records),
        file_name=f"{report_type.lower()}_reports.csv",
        mime="text/csv",
        use_container_width=True,
    )

    report_by_id = {int(record["id"]): record for record in report_records}
    archive = _group_reports_by_year_month(report_records)
    month_count = sum(len(months) for months in archive.values())
    st.markdown(
        f'<div class="report-archive-overview"><span>支持按月或按周收纳，展开后查看报告</span>'
        f'<strong>{len(report_records)} 份报告 · {len(archive)} 个年份 · {month_count} 个月份</strong></div>',
        unsafe_allow_html=True,
    )
    archive_years = tuple(archive)
    selected_year_key = "report_archive_selected_year"
    if st.session_state.get(selected_year_key) not in archive_years:
        st.session_state[selected_year_key] = archive_years[0]
    st.session_state.setdefault("report_archive_mode", "Month")
    with st.container(key="report_archive_selector"):
        year_col, mode_col, page_col = st.columns([0.9, 1.5, 0.7])
        selected_year = year_col.selectbox(
            "归档年份",
            options=archive_years,
            key=selected_year_key,
            format_func=lambda year: f"{year} 年",
        )
        selected_year_months = archive[int(selected_year)]
        archive_mode = mode_col.segmented_control(
            "收纳方式",
            options=("Month", "Week"),
            key="report_archive_mode",
            format_func=lambda value: "按月收纳" if value == "Month" else "按周收纳",
        ) or "Month"
        year_records = [
            record
            for month_records in selected_year_months.values()
            for record in month_records
        ]
        if archive_mode == "Week":
            period_groups = [
                (
                    f"week_{week_start.isoformat()}",
                    _week_archive_label(week_start, week_end, records),
                    records,
                )
                for week_start, week_end, records in _group_reports_by_week(year_records)
            ]
        else:
            period_groups = [
                (
                    f"month_{int(month):02d}",
                    _month_archive_label(int(month), records),
                    records,
                )
                for month, records in selected_year_months.items()
            ]
        page_count = max(
            1,
            (len(period_groups) + REPORT_ARCHIVE_GROUP_PAGE_SIZE - 1)
            // REPORT_ARCHIVE_GROUP_PAGE_SIZE,
        )
        page_key = f"report_archive_page_{report_type}_{selected_year}_{archive_mode}"
        page_options = tuple(range(1, page_count + 1))
        if st.session_state.get(page_key) not in page_options:
            st.session_state[page_key] = 1
        selected_page = page_col.selectbox(
            "页码",
            options=page_options,
            key=page_key,
            format_func=lambda page: f"{page}/{page_count}",
        )

    visible_groups, _, safe_page = _report_archive_page(
        period_groups,
        int(selected_page),
        page_size=REPORT_ARCHIVE_GROUP_PAGE_SIZE,
    )
    first_group = (safe_page - 1) * REPORT_ARCHIVE_GROUP_PAGE_SIZE + 1
    last_group = first_group + len(visible_groups) - 1
    mode_label = "按月收纳" if archive_mode == "Month" else "按周收纳"
    st.markdown(
        f'<div class="report-archive-page-meta">当前载入 {selected_year} 年 · {mode_label}'
        f' · 第 {safe_page}/{page_count} 页 · {first_group}–{last_group} / {len(period_groups)} 个归档组</div>',
        unsafe_allow_html=True,
    )
    with st.container(key="report_archive_tree"):
        for group_index, (group_key, group_label, group_records) in enumerate(visible_groups):
            with st.container(key=f"report_archive_group_{group_key}"):
                with st.expander(group_label, expanded=group_index == 0):
                    for record in group_records:
                        _render_report_archive_row(st, db_path, record)

    open_report_id = st.session_state.get("open_report_id")
    if open_report_id:
        selected_report = report_by_id.get(int(open_report_id))
        if selected_report is None:
            row = ReportRepository(db_path).get_by_id(int(open_report_id))
            selected_report = rows_to_records([row])[0] if row else None
        if selected_report:
            _render_report_dialog(st, selected_report)
