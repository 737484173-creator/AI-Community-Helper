from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from html import escape

import altair as alt
import pandas as pd

from app.bot.feedback_monitor import EXCLUDED_FEEDBACK_USER_IDS, MONITORED_FEEDBACK_CHANNELS, normalize_feedback_content
from app.dashboard.export_utils import records_to_csv
from app.dashboard.feedback_reply_service import FeedbackReplyService
from app.dashboard.formatters import date_range_to_datetimes, rows_to_records
from app.database.repositories.feedback_action_repository import FeedbackActionRepository
from app.database.repositories.feedback_repository import FeedbackRepository


FEEDBACK_STATUSES = ("Open", "In Progress", "Resolved", "Ignored")
FEEDBACK_CATEGORIES = (
    "All",
    "BUG",
    "GAMEPLAY_SUGGESTION",
    "BALANCE_ISSUE",
    "REWARD_ISSUE",
    "EVENT_SUGGESTION",
    "OTHER",
)
FEEDBACK_PRIORITIES = ("All", "High", "Medium", "Low")
STATUS_LABELS = {
    "All": "全部",
    "Open": "待处理",
    "In Progress": "处理中",
    "Resolved": "已解决",
    "Ignored": "忽略",
}
CATEGORY_LABELS = {
    "All": "全部",
    "BUG": "BUG",
    "GAMEPLAY_SUGGESTION": "玩法建议",
    "BALANCE_ISSUE": "平衡问题",
    "REWARD_ISSUE": "奖励问题",
    "EVENT_SUGGESTION": "活动建议",
    "OTHER": "其他",
}
PRIORITY_LABELS = {
    "All": "全部",
    "High": "高",
    "Medium": "中",
    "Low": "普通",
}
SLA_HOURS = {"High": 24, "Medium": 72, "Low": 168}
PAGE_SIZE_OPTIONS = (25, 50, 100)
FEEDBACK_CACHE_REVISION_KEY = "_feedback_center_cache_revision"


def _feedback_cache_revision(st) -> int:
    return int(st.session_state.setdefault(FEEDBACK_CACHE_REVISION_KEY, 0))


def _clear_feedback_caches(st) -> None:
    st.session_state[FEEDBACK_CACHE_REVISION_KEY] = _feedback_cache_revision(st) + 1


def _consume_dialog_request(st, key: str):
    """Return and clear a one-shot dialog request from session state."""
    return st.session_state.pop(key, None)


def _cached_open_counts(st, db_path, month_start: str, status_end: str) -> dict[str, int]:
    @st.cache_data(ttl=20, show_spinner=False)
    def _load(path: str, start: str, end: str, cache_revision: int) -> dict[str, int]:
        return FeedbackRepository(path).count_open_by_date_between(
            start,
            end,
            channel_names=MONITORED_FEEDBACK_CHANNELS,
            excluded_user_ids=EXCLUDED_FEEDBACK_USER_IDS,
        )

    return _load(str(db_path), month_start, status_end, _feedback_cache_revision(st))


def _cached_resolved_count(st, db_path) -> int:
    @st.cache_data(ttl=20, show_spinner=False)
    def _load(path: str, cache_revision: int) -> int:
        return FeedbackRepository(path).count_by_status(
            "Resolved",
            channel_names=MONITORED_FEEDBACK_CHANNELS,
            excluded_user_ids=EXCLUDED_FEEDBACK_USER_IDS,
        )

    return _load(str(db_path), _feedback_cache_revision(st))


def _cached_feedback_rows(
    st,
    db_path,
    start_time,
    end_time,
    category: str,
    priority: str,
    status_filter: str,
    limit: int = 500,
) -> list[dict]:
    @st.cache_data(ttl=20, show_spinner=False)
    def _load(
        path: str,
        start_value,
        end_value,
        selected_category: str,
        selected_priority: str,
        selected_status: str,
        row_limit: int,
        cache_revision: int,
    ) -> list[dict]:
        rows = FeedbackRepository(path).list_filtered(
            start_time=start_value,
            end_time=end_value,
            category=selected_category,
            priority=selected_priority,
            status=selected_status,
            channel_names=MONITORED_FEEDBACK_CHANNELS,
            excluded_user_ids=EXCLUDED_FEEDBACK_USER_IDS,
            limit=row_limit,
        )
        return rows_to_records(rows)

    return _load(
        str(db_path),
        start_time,
        end_time,
        category,
        priority,
        status_filter,
        limit,
        _feedback_cache_revision(st),
    )


def _month_bounds(target_date: date) -> tuple[date, date]:
    last_day = calendar.monthrange(target_date.year, target_date.month)[1]
    return date(target_date.year, target_date.month, 1), date(target_date.year, target_date.month, last_day)


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _compact_datetime(value: object) -> str:
    parsed = _parse_datetime(value)
    if not parsed:
        return str(value or "-")
    return parsed.strftime("%Y/%m/%d %H:%M")


def _short_text(value: object, limit: int = 72) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text or "-"
    return text[: limit - 1] + "…"


def _channel(record: dict) -> str:
    return str(record.get("display_channel_name") or record.get("channel_name") or "未知来源")


def _player(record: dict) -> str:
    return str(record.get("discord_user_name") or record.get("discord_user_id") or "未知玩家")


def _server(record: dict) -> str:
    title = str(record.get("thread_title") or "").strip()
    if title:
        return title
    channel = _channel(record)
    return channel if channel != "未知来源" else "-"


def _source_channel(record: dict) -> str:
    channel = _channel(record)
    return channel if channel != "未知来源" else "-"


def _status(record: dict) -> str:
    return str(record.get("status") or "Open")


def _priority(record: dict) -> str:
    return str(record.get("priority") or "Low")


def _owner(record: dict) -> str:
    return str(__import__("streamlit").session_state.get(f"feedback_owner_{record.get('id')}", "未分配"))


def _is_overdue(record: dict, now: datetime | None = None) -> bool:
    if _status(record) not in ("Open", "In Progress"):
        return False
    created = _parse_datetime(record.get("created_time"))
    if not created:
        return False
    threshold = SLA_HOURS.get(_priority(record), 168)
    return ((now or datetime.now()) - created).total_seconds() > threshold * 3600


def _similarity_key(record: dict) -> str:
    normalized = normalize_feedback_content(str(record.get("content") or ""))
    if normalized:
        return normalized
    return f"{record.get('category')}:{record.get('feature')}:{record.get('thread_title')}"


def _similar_groups(records: list[dict]) -> dict[int, list[dict]]:
    groups: dict[int, list[dict]] = {}
    normalized = [(record, _similarity_key(record)) for record in records]
    for record, key in normalized:
        matches = []
        for other, other_key in normalized:
            if not key or not other_key:
                continue
            if record.get("category") != other.get("category"):
                continue
            if SequenceMatcher(None, key, other_key).ratio() >= 0.82:
                matches.append(other)
        groups[int(record.get("id") or 0)] = matches or [record]
    return groups


def _collapse_thread_feedback(records: list[dict]) -> list[dict]:
    """Keep the earliest captured feedback for each Discord thread."""
    representatives: dict[tuple[str, str], dict] = {}
    standalone: list[dict] = []
    for record in records:
        thread_title = str(record.get("thread_title") or "").strip()
        if not thread_title:
            standalone.append(record)
            continue

        key = (
            str(record.get("channel_name") or record.get("display_channel_name") or "").strip().lower(),
            thread_title.lower(),
        )
        existing = representatives.get(key)
        record_order = (
            _parse_datetime(record.get("created_time")) or datetime.max,
            int(record.get("id") or 0),
        )
        existing_order = (
            _parse_datetime(existing.get("created_time")) or datetime.max,
            int(existing.get("id") or 0),
        ) if existing else None
        if existing is None or record_order < existing_order:
            representatives[key] = record

    selected_ids = {int(record.get("id") or 0) for record in representatives.values()}
    selected_ids.update(int(record.get("id") or 0) for record in standalone)
    return [record for record in records if int(record.get("id") or 0) in selected_ids]


def _feedback_css(st) -> None:
    st.markdown(
        """
        <style>
        .feedback-overview{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:10px 0 16px;}
        .feedback-card{min-height:76px;padding:14px 16px;border-radius:14px;border:1px solid rgba(0,0,0,.08);background:rgba(255,255,255,.86);}
        .feedback-card-label{font-size:12px;color:#6E6E73;line-height:18px;}
        .feedback-card-value{font-size:26px;font-weight:650;line-height:32px;color:#1D1D1F;margin-top:2px;}
        .feedback-card-helper{font-size:12px;color:#8A94A3;margin-top:3px;}
        .feedback-filter-shell{padding:16px;border-radius:14px;border:1px solid rgba(0,0,0,.08);background:rgba(255,255,255,.74);margin:10px 0 16px;}
        .feedback-filter-card{background:#F8FAFC;border:1px solid #E6EAF0;border-radius:14px;padding:16px;margin:10px 0 16px;}
        .feedback-filter-card [data-testid="stTextInput"] input,
        .feedback-filter-card [data-testid="stSelectbox"] div[data-baseweb="select"] > div,
        .feedback-filter-card [data-testid="stDateInput"] input{min-height:40px!important;border-radius:9px!important;}
        .feedback-filter-tags{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;}
        .feedback-filter-tag{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 10px;border-radius:999px;background:#EEF5FF;color:#2563EB;font-size:12px;border:1px solid rgba(37,99,235,.18);}
        .feedback-queue-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin:0;}
        .feedback-queue-title{font-size:20px;font-weight:650;color:#1D1D1F;line-height:28px;}
        .feedback-queue-caption{font-size:13px;color:#6E6E73;margin-top:2px;}
        .feedback-table{border:1px solid #E6EAF0;border-radius:14px;overflow:hidden;background:#fff;}
        .feedback-table-header{display:grid;grid-template-columns:.36fr 2.35fr .8fr .72fr 1.45fr .72fr .86fr .95fr .72fr;align-items:center;gap:10px;padding:0 12px;}
        .feedback-table-header{height:40px;background:#F8FAFC;color:#6E6E73;font-size:12px;font-weight:650;border-bottom:1px solid #E6EAF0;}
        .feedback-table-header>div{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
        [class*="st-key-feedback_row_"]{padding:8px 12px;border-bottom:1px solid #EDF1F6;background:#fff;color:#1D1D1F;font-size:13px;transition:background-color 160ms ease,box-shadow 160ms ease;}
        [class*="st-key-feedback_row_"]:last-child{border-bottom:none;}
        [class*="st-key-feedback_row_"]:hover{background:#FAFCFF;box-shadow:inset 0 0 0 1px rgba(0,113,227,.08);}
        [class*="st-key-feedback_row_"]:has(input:checked){background:#EEF5FF;box-shadow:inset 3px 0 0 #0071E3;border-radius:0;}
        .feedback-summary-main{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;line-height:18px;font-weight:600;}
        .feedback-summary-meta,.feedback-player-sub{font-size:12px;color:#8A94A3;line-height:18px;margin-top:2px;}
        .feedback-player-main{font-weight:600;line-height:18px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
        .feedback-tag{display:inline-flex;align-items:center;height:24px;padding:0 9px;border-radius:999px;font-size:12px;font-weight:650;white-space:nowrap;border:1px solid transparent;}
        .feedback-tag.bug{background:#F0EDFF;color:#5E5CE6;border-color:#DCD7FF;}
        .feedback-tag.event{background:#EAF8F0;color:#248A4B;border-color:#CFEEDB;}
        .feedback-tag.neutral{background:#EEF2F7;color:#5E6A7D;border-color:#DEE5EE;}
        .feedback-tag.high{background:#FFF0EF;color:#D92D20;border-color:#FFD4D0;}
        .feedback-tag.medium{background:#FFF4E5;color:#B85C00;border-color:#FFE0B2;}
        .feedback-tag.low{background:#EEF4FA;color:#52677A;border-color:#DCE7F1;}
        .feedback-tag.open{background:#FFF4E5;color:#B85C00;border-color:#FFE0B2;}
        .feedback-tag.progress{background:#EAF3FF;color:#006EDB;border-color:#CFE3FF;}
        .feedback-tag.waiting{background:#F0EDFF;color:#5E5CE6;border-color:#DCD7FF;}
        .feedback-tag.resolved{background:#EAF8F0;color:#248A4B;border-color:#CFEEDB;}
        .feedback-tag.ignored{background:#F2F4F7;color:#667085;border-color:#E4E7EC;}
        .feedback-similar-link{border:none;background:transparent;color:#0071E3;font-size:13px;padding:0;cursor:pointer;}
        .feedback-pagination{display:flex;align-items:center;gap:8px;margin:0;color:#6E6E73;font-size:13px;line-height:20px;white-space:nowrap;}
        .feedback-pagination strong{color:#1D1D1F;font-weight:650;}
        .feedback-bulk-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px;margin:10px 0;border-radius:14px;border:1px solid rgba(0,113,227,.18);background:rgba(0,113,227,.07);}
        .feedback-section-title{font-size:20px;font-weight:650;color:#1D1D1F;line-height:28px;margin:8px 0 2px;}
        .feedback-section-caption{font-size:13px;color:#6E6E73;margin-bottom:8px;}
        .feedback-detail-panel{padding:6px 2px;}
        .feedback-detail-head{position:sticky;top:0;z-index:2;padding:14px 0 12px;background:rgba(255,255,255,.98);border-bottom:1px solid rgba(0,0,0,.08);}
        .feedback-detail-title{font-size:20px;font-weight:650;color:#1D1D1F;line-height:28px;margin:8px 0 4px;}
        .feedback-detail-meta{font-size:12px;color:#6E6E73;line-height:20px;}
        .feedback-message{padding:14px;border-radius:14px;border:1px solid rgba(0,0,0,.06);background:rgba(245,247,250,.9);font-size:14px;line-height:22px;color:#1D1D1F;white-space:pre-wrap;}
        .feedback-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:12px;}
        .feedback-cell{padding:10px 12px;border-radius:12px;background:rgba(245,247,250,.78);font-size:13px;color:#1D1D1F;}
        .feedback-cell span{display:block;font-size:12px;color:#8A94A3;margin-bottom:4px;}
        .feedback-history{margin-top:16px;border-top:1px solid var(--border);}
        .feedback-history-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 2px 8px;font-size:13px;font-weight:650;color:var(--text-primary);}
        .feedback-history-count{font-size:12px;font-weight:550;color:var(--text-tertiary);}
        .feedback-history-item{position:relative;display:grid;grid-template-columns:118px minmax(0,1fr);gap:16px;padding:14px 2px 14px 18px;border-bottom:1px solid var(--border);}
        .feedback-history-item::before{content:"";position:absolute;left:2px;top:20px;width:7px;height:7px;border-radius:999px;background:var(--primary);box-shadow:0 0 0 4px var(--primary-soft);}
        .feedback-history-kind{font-size:13px;font-weight:650;color:var(--text-primary);}
        .feedback-history-time{margin-top:3px;font-size:11px;color:var(--text-tertiary);font-variant-numeric:tabular-nums;}
        .feedback-history-content{font-size:13px;line-height:20px;color:var(--text-primary);white-space:pre-wrap;overflow-wrap:anywhere;}
        .feedback-history-meta{display:flex;gap:10px;flex-wrap:wrap;margin-top:7px;font-size:11px;color:var(--text-tertiary);}
        .feedback-topic-card{padding:14px 16px;border-radius:14px;border:1px solid rgba(0,0,0,.08);background:rgba(255,255,255,.84);margin-bottom:10px;}
        .feedback-topic-title{font-size:15px;font-weight:650;color:#1D1D1F;margin-bottom:8px;}
        .feedback-topic-meta{font-size:12px;color:#6E6E73;display:flex;gap:8px;flex-wrap:wrap;}
        .feedback-calendar-title{font-size:18px;font-weight:650;color:#1D1D1F;margin:4px 0 14px;}
        .feedback-calendar{display:grid;grid-template-columns:repeat(7,minmax(42px,1fr));gap:8px;padding:4px 0 8px;}
        .feedback-calendar-weekday{font-size:12px;color:#8A94A3;text-align:center;}
        .feedback-calendar-day{min-height:48px;border:1px solid rgba(0,0,0,.08);border-radius:10px;background:rgba(255,255,255,.8);display:flex;align-items:center;justify-content:center;gap:6px;color:#1D1D1F;}
        .feedback-calendar-day.today{border-color:#0071E3;background:rgba(0,113,227,.06);}
        .feedback-calendar-day.empty{background:transparent;border-color:transparent;}
        .feedback-calendar-risk{min-width:18px;height:18px;padding:0 6px;border-radius:999px;background:#FF3B30;color:white;font-size:11px;line-height:18px;text-align:center;}
        .feedback-zero-state{min-height:78px;display:flex;align-items:center;padding:0 18px;border-radius:14px;border:1px solid rgba(52,199,89,.22);background:rgba(52,199,89,.08);font-size:14px;color:#1D1D1F;}
        .feedback-insight-card{padding:16px;border-radius:14px;border:1px solid #E6EAF0;background:#fff;margin-bottom:14px;}
        .feedback-insight-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px;}
        .feedback-insight-title{font-size:18px;font-weight:650;color:#1D1D1F;line-height:26px;}
        .feedback-insight-subtitle{font-size:13px;color:#6E6E73;line-height:20px;margin-top:2px;}
        .feedback-insight-metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:12px 0 14px;}
        .feedback-insight-metric{height:78px;padding:12px 14px;border-radius:14px;border:1px solid #E6EAF0;background:#fff;}
        .feedback-insight-metric-label{font-size:12px;color:#6E6E73;line-height:18px;}
        .feedback-insight-metric-value{font-size:22px;font-weight:650;color:#1D1D1F;line-height:28px;margin-top:2px;}
        .feedback-insight-metric-help{font-size:12px;color:#8A94A3;margin-top:2px;}
        .feedback-topic-table{border:1px solid #E6EAF0;border-radius:14px;overflow:hidden;background:#fff;}
        .feedback-topic-row,.feedback-topic-header{display:grid;grid-template-columns:minmax(260px,2fr) 90px 100px 130px 110px;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid #EDF1F6;font-size:13px;}
        .feedback-topic-header{background:#F8FAFC;color:#6E6E73;font-size:12px;font-weight:650;}
        .feedback-topic-row:last-child{border-bottom:none;}
        .feedback-overview{
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:0;
            margin:8px 0 22px;
            overflow:hidden;
            border-top:1px solid var(--border-strong);
            border-bottom:1px solid var(--border);
            background:color-mix(in srgb,var(--surface) 58%,transparent);
            animation:content-enter var(--motion-enter) var(--ease-standard) both;
        }
        .feedback-card{
            position:relative;
            min-width:0;
            min-height:100px;
            padding:16px 18px 15px;
            border:0;
            border-radius:0;
            background:transparent;
            transition:
                background-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        .feedback-card+.feedback-card{border-left:1px solid var(--border);}
        .feedback-card:nth-child(2){background:color-mix(in srgb,var(--warning-soft) 24%,transparent);}
        .feedback-card:hover{
            background:color-mix(in srgb,var(--primary-soft) 40%,var(--surface));
            box-shadow:inset 0 -2px 0 color-mix(in srgb,var(--primary) 58%,transparent);
        }
        .feedback-card:nth-child(2):hover{background:color-mix(in srgb,var(--warning-soft) 58%,var(--surface));}
        .feedback-card-value{
            display:inline-block;
            font-size:30px;
            line-height:34px;
            font-variant-numeric:tabular-nums;
            letter-spacing:-.035em;
            transform-origin:left center;
            transition:
                transform var(--motion-standard) var(--ease-standard),
                color var(--motion-standard) var(--ease-standard);
        }
        .feedback-card:hover .feedback-card-value{
            color:var(--primary-hover);
            transform:translateY(-1px) scale(1.025);
        }
        .feedback-overview{
            transform:translateY(0);
            transition:
                transform var(--motion-standard) var(--ease-standard),
                border-color var(--motion-standard) var(--ease-standard),
                background-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        .feedback-overview:hover{
            transform:translateY(-2px);
            border-color:color-mix(in srgb,var(--primary) 22%,var(--border));
            background:color-mix(in srgb,var(--primary-soft) 14%,var(--surface));
            box-shadow:var(--shadow-2);
        }
        .feedback-insight-card{
            padding:16px 0;
            border:0;
            border-top:1px solid var(--border-strong);
            border-bottom:1px solid var(--border);
            border-radius:0;
            background:transparent;
        }
        .feedback-topic-card,.feedback-table,.feedback-topic-table{background:var(--surface);border-color:var(--border);border-radius:var(--radius-card);}
        .feedback-card-label,.feedback-queue-caption,.feedback-detail-meta,.feedback-insight-subtitle,.feedback-topic-meta,.feedback-pagination{color:var(--text-secondary);}
        .feedback-card-helper,.feedback-summary-meta,.feedback-player-sub,.feedback-cell span,.feedback-insight-metric-help,.feedback-calendar-weekday{color:var(--text-tertiary);}
        .feedback-card-value,.feedback-queue-title,.feedback-section-title,.feedback-detail-title,.feedback-insight-title,.feedback-insight-metric-value{color:var(--text-primary);}
        div.stVerticalBlock.st-key-feedback_filter_panel{gap:16px;margin:12px 0 24px;padding:17px 0 14px;border-top:1px solid var(--border-strong);border-bottom:1px solid var(--border);}
        .feedback-filter-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:2px;}
        .feedback-filter-title{color:var(--text-primary);font-size:18px;font-weight:680;line-height:26px;letter-spacing:-.015em;}
        .feedback-filter-caption{margin-top:4px;color:var(--text-secondary);font-size:12px;line-height:18px;text-wrap:pretty;}
        .feedback-filter-mode{color:var(--text-tertiary);font-size:11px;font-weight:650;letter-spacing:.04em;white-space:nowrap;}
        div.stVerticalBlock.st-key-feedback_filter_command{gap:10px;padding:14px 16px 12px;border:1px solid color-mix(in srgb,var(--primary) 14%,var(--border));border-radius:var(--radius-card);background:color-mix(in srgb,var(--primary-soft) 18%,var(--surface));box-shadow:inset 0 1px 0 color-mix(in srgb,white 68%,transparent);}
        div.stVerticalBlock.st-key-feedback_filter_drawer{gap:0;margin-top:2px;padding-top:4px;border-top:1px solid color-mix(in srgb,var(--border) 82%,transparent);}
        [class*="st-key-feedback_filter_drawer"] details{border:0!important;border-radius:0!important;background:transparent!important;box-shadow:none!important;}
        [class*="st-key-feedback_filter_drawer"] details summary{min-height:42px;padding:0 2px!important;color:var(--text-secondary);transition:color var(--motion-standard) var(--ease-standard);}
        [class*="st-key-feedback_filter_drawer"] details summary:hover{color:var(--primary);}
        [class*="st-key-feedback_filter_drawer"] details[open] summary{border-bottom:1px solid var(--border);color:var(--text-primary);}
        [class*="st-key-feedback_filter_drawer"] details>div{padding:14px 0 2px!important;}
        div.stVerticalBlock.st-key-feedback_queue_panel{gap:12px;padding:18px 0 0;border:0;border-top:1px solid var(--border-strong);border-radius:0;background:transparent;box-shadow:none;}
        div.stVerticalBlock.st-key-feedback_queue_toolbar{gap:0;}
        div.stVerticalBlock.st-key-feedback_queue_pagination{gap:0;padding:10px 0 2px;border-top:1px solid color-mix(in srgb,var(--border) 78%,transparent);}
        div.stVerticalBlock.st-key-feedback_table_shell{container-type:inline-size;gap:0;border:1px solid var(--border);border-radius:var(--radius-card);overflow:hidden;background:var(--surface);}
        div.stVerticalBlock.st-key-feedback_select_all_bar{gap:0;min-height:38px;padding:6px 12px;background:color-mix(in srgb,var(--surface-muted) 78%,var(--surface));border-bottom:1px solid var(--border);}
        div.stVerticalBlock.st-key-feedback_select_all_bar [data-testid="stCheckbox"]{margin:0;}
        div.stVerticalBlock.st-key-feedback_select_all_bar label{font-size:12px;color:var(--text-secondary);}
        .feedback-filter-tags{margin-top:12px;}
        .feedback-filter-tag{height:26px;background:var(--primary-soft);color:var(--primary);border-color:color-mix(in srgb,var(--primary) 20%,var(--border));}
        .feedback-table-header,.feedback-topic-header{background:var(--surface-muted);color:var(--text-secondary);border-color:var(--border);}
        [class*="st-key-feedback_row_"]{border-color:color-mix(in srgb,var(--border) 72%,transparent);background:var(--surface);}
        [class*="st-key-feedback_row_"]:hover{background:color-mix(in srgb,var(--primary-soft) 34%,var(--surface));box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--primary) 10%,transparent);}
        [class*="st-key-feedback_row_"]:has(input:checked){background:var(--primary-soft);box-shadow:inset 3px 0 0 var(--primary);border-radius:0;}
        .feedback-bulk-bar{background:var(--primary-soft);border-color:color-mix(in srgb,var(--primary) 20%,var(--border));border-radius:var(--radius-control);}
        [class*="st-key-feedback_bulk_actions"]{position:sticky;top:12px;z-index:12;margin:12px 0;}
        [class*="st-key-feedback_bulk_actions"] [data-testid="stVerticalBlockBorderWrapper"]{padding:12px;background:color-mix(in srgb,var(--surface) 96%,transparent);border-color:var(--border-strong);border-radius:var(--radius-panel);box-shadow:var(--shadow-3);backdrop-filter:blur(10px);}
        [class*="st-key-feedback_bulk_actions"] .feedback-bulk-bar{margin:0 0 8px;padding:8px 10px;border:none;background:transparent;}
        .feedback-message,.feedback-cell{background:var(--surface-muted);border-color:var(--border);color:var(--text-primary);}
        .feedback-detail-head{background:var(--surface);border-color:var(--border);}
        .feedback-calendar-day{background:var(--surface);border-color:var(--border);color:var(--text-primary);}
        .feedback-calendar-day.today{border-color:var(--primary);background:var(--primary-soft);}
        .feedback-calendar-risk{background:var(--danger);}
        .feedback-zero-state{background:var(--success-soft);border-color:color-mix(in srgb,var(--success) 24%,var(--border));color:var(--success);}
        .feedback-insight-metrics{grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:0;overflow:hidden;border-top:1px solid var(--border);border-bottom:1px solid var(--border);}
        .feedback-insight-metric{height:auto;min-height:82px;padding:12px 14px;border:0;border-radius:0;background:transparent;}
        .feedback-insight-metric+.feedback-insight-metric{border-left:1px solid var(--border);}
        @media(max-width:1100px){
            .feedback-insight-metrics{grid-template-columns:repeat(2,minmax(0,1fr));}
            .feedback-insight-metric:nth-child(odd){border-left:0;}
            .feedback-insight-metric:nth-child(n+3){border-top:1px solid var(--border);}
            .feedback-insight-metric:last-child:nth-child(odd){grid-column:1/-1;}
        }
        @media(max-width:900px){
            .feedback-overview{grid-template-columns:repeat(2,minmax(0,1fr));}
            .feedback-card:nth-child(3){border-left:0;border-top:1px solid var(--border);}
            .feedback-card:nth-child(4){border-top:1px solid var(--border);}
            .feedback-grid{grid-template-columns:1fr;}
            .feedback-history-item{grid-template-columns:1fr;gap:7px;}
            div.stVerticalBlock.st-key-feedback_filter_command{padding:14px;}
        }
        @media(max-width:560px){.feedback-insight-metrics{grid-template-columns:1fr 1fr;gap:0;}.feedback-card{min-height:86px;padding:12px;}.feedback-filter-head{align-items:flex-start;flex-direction:column;gap:6px;}.feedback-queue-head{align-items:flex-start;flex-direction:column;}.feedback-calendar{gap:4px;}.feedback-calendar-day{min-height:42px;}}
        @media(max-width:768px){
            .feedback-table-header{display:none;}
            div.stVerticalBlock.st-key-feedback_queue_panel{padding-top:14px;}
            div.stVerticalBlock.st-key-feedback_table_shell{border:none;border-radius:0;background:transparent;overflow:visible;}
            div.stVerticalBlock.st-key-feedback_select_all_bar{border:1px solid var(--border);border-radius:var(--radius-control);margin-bottom:8px;}
            [class*="st-key-feedback_row_"]{margin:8px 0;padding:12px;border:1px solid var(--border);border-radius:var(--radius-card);background:var(--surface);}
            [class*="st-key-feedback_row_"] [data-testid="stHorizontalBlock"]{display:grid!important;grid-template-columns:32px repeat(3,minmax(0,1fr))!important;gap:8px!important;align-items:center!important;}
            [class*="st-key-feedback_row_"] [data-testid="stColumn"]{width:auto!important;min-width:0!important;flex:none!important;}
            [class*="st-key-feedback_row_"] [data-testid="stColumn"]:nth-child(1){grid-column:1;grid-row:1/span 4;align-self:start;}
            [class*="st-key-feedback_row_"] [data-testid="stColumn"]:nth-child(2){grid-column:2/-1;grid-row:1;}
            [class*="st-key-feedback_row_"] [data-testid="stColumn"]:nth-child(3){grid-column:2;grid-row:2;}
            [class*="st-key-feedback_row_"] [data-testid="stColumn"]:nth-child(7),
            [class*="st-key-feedback_row_"] [data-testid="stColumn"]:nth-child(8){display:none;}
            [class*="st-key-feedback_row_"] [data-testid="stColumn"]:nth-child(4){grid-column:3;grid-row:2;}
            [class*="st-key-feedback_row_"] [data-testid="stColumn"]:nth-child(5){grid-column:2/-1;grid-row:3;}
            [class*="st-key-feedback_row_"] [data-testid="stColumn"]:nth-child(6){grid-column:4;grid-row:2;}
            [class*="st-key-feedback_row_"] [data-testid="stColumn"]:nth-child(9){grid-column:2/-1;grid-row:4;}
            [class*="st-key-feedback_bulk_actions"]{top:8px;}
            [class*="st-key-feedback_bulk_actions"] .feedback-bulk-bar{align-items:flex-start;flex-direction:column;}
        }
        @media(prefers-reduced-motion:reduce){
            .feedback-overview,
            .feedback-card,
            .feedback-card-value{
                animation:none!important;
                transition:none!important;
            }
            .feedback-overview:hover,
            .feedback-card:hover .feedback-card-value{transform:none!important;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _build_feedback_calendar_html(target_month: date, today: date, open_counts: dict[str, int]) -> str:
    month_start, _ = _month_bounds(target_month)
    first_weekday, month_days = calendar.monthrange(month_start.year, month_start.month)
    cells: list[date | None] = [None] * first_weekday
    cells.extend(date(month_start.year, month_start.month, day) for day in range(1, month_days + 1))
    while len(cells) % 7:
        cells.append(None)
    weekday_cells = "".join(f"<div class='feedback-calendar-weekday'>{label}</div>" for label in ("一", "二", "三", "四", "五", "六", "日"))
    day_cells = []
    for cell_date in cells:
        if cell_date is None:
            day_cells.append("<div class='feedback-calendar-day empty'></div>")
            continue
        count = open_counts.get(cell_date.isoformat(), 0)
        today_class = " today" if cell_date == today else ""
        badge = f"<span class='feedback-calendar-risk'>{count}</span>" if count else ""
        day_cells.append(f"<div class='feedback-calendar-day{today_class}'><span>{cell_date.day}</span>{badge}</div>")
    return f"<div class='feedback-calendar-title'>{target_month.year} 年 {target_month.month} 月</div><div class='feedback-calendar'>{weekday_cells}{''.join(day_cells)}</div>"


def _render_calendar_dialog(st, db_path) -> None:
    @st.dialog("日历视图", width="large")
    def calendar_dialog() -> None:
        today = date.today()
        current_start = st.session_state.get("feedback_start_date", today)
        month_start, month_end = _month_bounds(current_start)
        open_counts = _cached_open_counts(st, db_path, month_start.isoformat(), min(month_end, today).isoformat())
        st.caption("蓝色描边表示今天，红色数字表示当天仍有未处理反馈。")
        st.markdown(_build_feedback_calendar_html(current_start, today, open_counts), unsafe_allow_html=True)
        if st.button("关闭", use_container_width=True):
            st.session_state["feedback_calendar_open"] = False
            st.rerun()

    calendar_dialog()


def _overview(st, repository: FeedbackRepository, db_path) -> None:
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=6)
    today_start, today_end = date_range_to_datetimes(today, today)
    yesterday_start, yesterday_end = date_range_to_datetimes(yesterday, yesterday)
    week_start_time, week_end_time = date_range_to_datetimes(week_start, today)
    today_count = repository.count_between(today_start, today_end)
    yesterday_count = repository.count_between(yesterday_start, yesterday_end)
    open_rows = _collapse_thread_feedback(rows_to_records(repository.list_open()))
    open_count = len(open_rows)
    high_count = sum(1 for row in open_rows if str(row["priority"]) == "High")
    week_rows = _cached_feedback_rows(st, db_path, week_start_time, week_end_time, "All", "All", "Resolved", 10000)
    week_resolved = len(week_rows)
    resolved_total = max(_cached_resolved_count(st, db_path), week_resolved)
    delta = today_count - yesterday_count
    delta_text = "较昨日持平" if delta == 0 else f"较昨日 {'+' if delta > 0 else ''}{delta}"
    overdue = sum(1 for row in open_rows if _is_overdue(row))
    cards = [
        ("今日新增", today_count, delta_text),
        ("待处理", open_count, f"已超时 {overdue} 条"),
        ("需优先查看", high_count, "高优先级与疑似重复 BUG"),
        ("本周已解决", week_resolved, f"累计已解决 {resolved_total} 条"),
    ]
    st.markdown(
        "<div class='feedback-overview'>"
        + "".join(
            f"<div class='feedback-card'><div class='feedback-card-label'>{escape(label)}</div><div class='feedback-card-value'>{value}</div><div class='feedback-card-helper'>{escape(helper)}</div></div>"
            for label, value, helper in cards
        )
        + "</div>",
        unsafe_allow_html=True,
    )


def _reset_feedback_filters() -> None:
    st_state = __import__("streamlit").session_state
    today = date.today()
    st_state["feedback_quick_range"] = "今天"
    st_state["feedback_start_date"] = today
    st_state["feedback_end_date"] = today


def _render_filters(st) -> tuple[date, date, str, str, str, str, bool]:
    today = date.today()
    st.session_state.setdefault("feedback_quick_range", "今天")
    with st.container(key="feedback_filter_panel"):
        st.markdown(
            """
            <div class="feedback-filter-head">
                <div>
                    <div class="feedback-filter-title">反馈检索台</div>
                    <div class="feedback-filter-caption">常用检索保持在前，分类与处理条件按需展开。</div>
                </div>
                <span class="feedback-filter-mode">实时联动</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.container(key="feedback_filter_command"):
            keyword_col, range_col, merge_col, query_col, reset_col = st.columns([2.2, 1.55, 1.1, 0.75, 0.75], vertical_alignment="bottom")
            keyword = keyword_col.text_input("关键词搜索", value="", placeholder="搜索玩家、区服、频道、标题或反馈内容")
            quick_range = range_col.segmented_control("日期范围", options=("今天", "近7天", "近30天", "自定义"), key="feedback_quick_range")
            merge_similar = merge_col.toggle("合并相似反馈", value=False)
            query_col.button("查询", use_container_width=True, type="primary")
            reset_col.button("重置", use_container_width=True, on_click=_reset_feedback_filters)
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
                st.session_state.setdefault("feedback_start_date", today)
                st.session_state.setdefault("feedback_end_date", today)
                start_date = date_left.date_input("开始日期", key="feedback_start_date")
                end_date = date_right.date_input("结束日期", key="feedback_end_date")
            with st.container(key="feedback_filter_drawer"):
                with st.expander("更多条件 · 分类 / 优先级 / 状态", expanded=False):
                    category_col, priority_col, status_col = st.columns(3)
                    category = category_col.selectbox("分类", FEEDBACK_CATEGORIES, format_func=lambda value: CATEGORY_LABELS[value])
                    priority = priority_col.selectbox("优先级", FEEDBACK_PRIORITIES, format_func=lambda value: PRIORITY_LABELS[value])
                    status = status_col.selectbox("状态", ("All", *FEEDBACK_STATUSES), format_func=lambda value: STATUS_LABELS[value])
        active_tags = []
        if quick_range != "今天":
            active_tags.append(f"日期：{quick_range}")
        if keyword.strip():
            active_tags.append(f"关键词：{keyword.strip()}")
        if category != "All":
            active_tags.append(f"分类：{CATEGORY_LABELS[category]}")
        if priority != "All":
            active_tags.append(f"优先级：{PRIORITY_LABELS[priority]}")
        if status != "All":
            active_tags.append(f"状态：{STATUS_LABELS[status]}")
        if merge_similar:
            active_tags.append("合并相似反馈")
        if active_tags:
            st.markdown(
                "<div class='feedback-filter-tags'>"
                + "".join(f"<span class='feedback-filter-tag'>{escape(tag)}</span>" for tag in active_tags)
                + "</div>",
                unsafe_allow_html=True,
            )
    return start_date, end_date, category, priority, status, keyword, merge_similar


def _filter_keyword(records: list[dict], keyword: str) -> list[dict]:
    output = records
    if keyword.strip():
        needle = keyword.strip().lower()
        output = [record for record in output if needle in " ".join(str(value).lower() for value in record.values())]
    return output


def _dedupe_similar(records: list[dict]) -> list[dict]:
    seen: list[str] = []
    output = []
    for record in records:
        key = _similarity_key(record)
        if any(SequenceMatcher(None, key, old_key).ratio() >= 0.9 for old_key in seen):
            continue
        seen.append(key)
        output.append(record)
    return output


def _category_tone(category: str) -> str:
    if category == "BUG":
        return "bug"
    if category == "EVENT_SUGGESTION":
        return "event"
    return "neutral"


def _status_tone(status: str) -> str:
    if status == "Open":
        return "open"
    if status == "In Progress":
        return "progress"
    if status == "Resolved":
        return "resolved"
    if status == "Ignored":
        return "ignored"
    return "waiting"


def _html_tag(label: str, tone: str) -> str:
    return f"<span class='feedback-tag {tone}'>{escape(label)}</span>"


def _feedback_thread_title(record: dict) -> str:
    title = " ".join(str(record.get("thread_title") or "").split())
    return title or "未命名帖子"


def _player_display(record: dict) -> tuple[str, str]:
    player = _player(record)
    user_id = str(record.get("discord_user_id") or "-")
    short_id = user_id if len(user_id) <= 8 else f"{user_id[:4]}…{user_id[-4:]}"
    channel = _source_channel(record)
    channel_text = f"#{channel}" if channel != "-" else channel
    return player, f"{channel_text} · {short_id}"


def _queue_table_records(records: list[dict], groups: dict[int, list[dict]]) -> list[dict]:
    rows = []
    for record in records:
        feedback_id = int(record.get("id") or 0)
        priority = _priority(record)
        rows.append(
            {
                "选择": False,
                "ID": feedback_id,
                "反馈摘要": _short_text(record.get("content"), 68),
                "分类": CATEGORY_LABELS.get(str(record.get("category")), str(record.get("category") or "-")),
                "相似反馈数量": len(groups.get(feedback_id, [record])),
                "优先级": PRIORITY_LABELS.get(priority, priority),
                "玩家和区服": f"{_player(record)} / {_server(record)}",
                "最近反馈时间": _compact_datetime(record.get("created_time")),
                "状态": STATUS_LABELS.get(_status(record), _status(record)),
                "负责人": _owner(record),
                "操作": "查看详情",
                "SLA": "已超时" if _is_overdue(record) else "正常",
            }
        )
    return rows


def _export_records(records: list[dict], groups: dict[int, list[dict]]) -> list[dict]:
    return _queue_table_records(records, groups)


def _bulk_update_status(
    repository: FeedbackRepository,
    selected_ids: list[int],
    status: str,
) -> int:
    for feedback_id in selected_ids:
        repository.update_thread_status(feedback_id, status)
    return len(selected_ids)


def _clear_feedback_selection(st, selected_ids: list[int]) -> None:
    st.session_state["feedback_select_all_visible"] = False
    for feedback_id in selected_ids:
        st.session_state[f"feedback_selected_{feedback_id}"] = False


def _bulk_bar(st, db_path, selected_ids: list[int]) -> None:
    if not selected_ids:
        return
    with st.container(key="feedback_bulk_actions", border=True):
        st.markdown(
            f"<div class='feedback-bulk-bar'><strong>已选中 {len(selected_ids)} 条反馈</strong>"
            "<span>同一帖子会作为一个事项统一更新</span></div>",
            unsafe_allow_html=True,
        )
        pending_col, resolved_col, help_col = st.columns([1, 1, 2.4], vertical_alignment="center")
        repository = FeedbackRepository(db_path)
        if pending_col.button("设为待分配", key="bulk_feedback_open", use_container_width=True):
            updated = _bulk_update_status(repository, selected_ids, "Open")
            for feedback_id in selected_ids:
                st.session_state.pop(f"feedback_owner_{feedback_id}", None)
            _clear_feedback_selection(st, selected_ids)
            st.session_state["feedback_bulk_notice"] = f"已将 {updated} 个反馈事项设为待分配。"
            _clear_feedback_caches(st)
            st.rerun(scope="app")
        if resolved_col.button("标记已解决", key="bulk_feedback_resolved", type="primary", use_container_width=True):
            updated = _bulk_update_status(repository, selected_ids, "Resolved")
            _clear_feedback_selection(st, selected_ids)
            st.session_state["feedback_bulk_notice"] = f"已将 {updated} 个反馈事项标记为已解决。"
            _clear_feedback_caches(st)
            st.rerun(scope="app")
        help_col.caption("待分配会恢复为待处理状态并清除当前页面中的负责人；已解决会同步更新同一帖子的历史重复记录。")


def _render_queue_header(st, total_count: int, rows: list[dict], groups: dict[int, list[dict]]) -> None:
    notice = st.session_state.pop("feedback_bulk_notice", None)
    if notice:
        st.success(notice)
    with st.container(key="feedback_queue_toolbar"):
        left, sync_col, export_col = st.columns([4, 0.8, 1], vertical_alignment="center")
        left.markdown(
            f"<div class='feedback-queue-title'>待处理队列 · {total_count} 条</div><div class='feedback-queue-caption'>点击行内“查看”打开反馈详情，勾选后显示批量操作。</div>",
            unsafe_allow_html=True,
        )
        if sync_col.button("同步", use_container_width=True):
            _clear_feedback_caches(st)
            st.rerun()
        export_col.download_button(
            "导出 CSV",
            data=records_to_csv(_export_records(rows, groups)),
            file_name="feedback_center.csv",
            mime="text/csv",
            use_container_width=True,
        )


def _render_feedback_table(st, page_rows: list[dict], groups: dict[int, list[dict]]) -> list[int]:
    if not page_rows:
        return []

    visible_ids = [int(record.get("id") or 0) for record in page_rows]

    def _toggle_visible_feedback() -> None:
        checked = bool(st.session_state.get("feedback_select_all_visible", False))
        for feedback_id in visible_ids:
            st.session_state[f"feedback_selected_{feedback_id}"] = checked

    selected_ids: list[int] = []
    with st.container(key="feedback_table_shell"):
        with st.container(key="feedback_select_all_bar"):
            st.checkbox(
                "选择当前页全部反馈",
                key="feedback_select_all_visible",
                on_change=_toggle_visible_feedback,
            )
        st.markdown(
            "<div class='feedback-table-header'>"
            "<div></div><div>帖子标题</div><div>分类</div><div>优先级</div>"
            "<div>玩家和来源</div><div>状态</div><div>负责人</div><div>最近更新</div><div>操作</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        for record in page_rows:
            feedback_id = int(record.get("id") or 0)
            checkbox_key = f"feedback_selected_{feedback_id}"
            player, player_sub = _player_display(record)
            category = str(record.get("category") or "OTHER")
            priority = _priority(record)
            status = _status(record)
            updated = record.get("updated_time") or record.get("created_time")
            thread_title = _feedback_thread_title(record)

            with st.container(key=f"feedback_row_{feedback_id}"):
                cols = st.columns([0.36, 2.35, 0.8, 0.72, 1.45, 0.72, 0.86, 0.95, 0.72], vertical_alignment="center")
                checked = cols[0].checkbox(f"选择反馈 {feedback_id}", key=checkbox_key, label_visibility="collapsed")
                if checked:
                    selected_ids.append(feedback_id)
                summary_html = (
                    f"<div title='{escape(thread_title)}'>"
                    f"<div class='feedback-summary-main'>{escape(_short_text(thread_title, 92))}</div></div>"
                )
                cols[1].markdown(summary_html, unsafe_allow_html=True)
                cols[2].markdown(_html_tag(CATEGORY_LABELS.get(category, category), _category_tone(category)), unsafe_allow_html=True)
                cols[3].markdown(_html_tag(PRIORITY_LABELS.get(priority, priority), _priority_tone(priority)), unsafe_allow_html=True)
                cols[4].markdown(
                    f"<div title='{escape(str(record.get('discord_user_id') or '-'))}'><div class='feedback-player-main'>{escape(player)}</div><div class='feedback-player-sub'>{escape(player_sub)}</div></div>",
                    unsafe_allow_html=True,
                )
                cols[5].markdown(_html_tag(STATUS_LABELS.get(status, status), _status_tone(status)), unsafe_allow_html=True)
                cols[6].markdown(f"<span class='feedback-summary-meta'>{escape(_owner(record))}</span>", unsafe_allow_html=True)
                cols[7].markdown(f"<span class='feedback-summary-meta'>{escape(_compact_datetime(updated))}</span>", unsafe_allow_html=True)
                if cols[8].button("查看", key=f"open_feedback_{feedback_id}", use_container_width=True):
                    st.session_state["feedback_detail_id"] = feedback_id
                    st.rerun(scope="app")
    return sorted(set(selected_ids))


def _render_feedback_workspace(st, db_path, page_rows: list[dict], groups: dict[int, list[dict]]) -> None:
    @st.fragment
    def feedback_workspace() -> None:
        selected_ids = sorted(
            int(record.get("id") or 0)
            for record in page_rows
            if st.session_state.get(f"feedback_selected_{int(record.get('id') or 0)}", False)
        )
        _bulk_bar(st, db_path, selected_ids)
        _render_feedback_table(st, page_rows, groups)

    feedback_workspace()


def _pagination_controls(st, total_count: int) -> tuple[int, int]:
    st.session_state.setdefault("feedback_page_size", 25)
    st.session_state.setdefault("feedback_page_number", 1)
    page_size = int(st.session_state.get("feedback_page_size", 25))
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    current_page = min(int(st.session_state.get("feedback_page_number", 1)), total_pages)
    st.session_state["feedback_page_number"] = current_page
    start_index = (current_page - 1) * page_size
    end_index = min(start_index + page_size, total_count)
    with st.container(key="feedback_queue_pagination"):
        summary_col, range_col, previous_col, next_col, size_col = st.columns(
            [2.5, 0.9, 0.9, 0.9, 2.1],
            vertical_alignment="center",
        )
        summary_col.markdown(
            f"<div class='feedback-pagination'><strong>{total_count}</strong> 条反馈</div>",
            unsafe_allow_html=True,
        )
        range_col.markdown(
            f"<div class='feedback-pagination'>{start_index + 1 if total_count else 0}-{end_index} / {total_count}</div>",
            unsafe_allow_html=True,
        )
        if previous_col.button("上一页", disabled=current_page <= 1, use_container_width=True):
            st.session_state["feedback_page_number"] = max(1, current_page - 1)
            st.rerun()
        if next_col.button("下一页", disabled=current_page >= total_pages, use_container_width=True):
            st.session_state["feedback_page_number"] = min(total_pages, current_page + 1)
            st.rerun()
        size_col.segmented_control(
            "每页数量",
            options=PAGE_SIZE_OPTIONS,
            key="feedback_page_size",
            format_func=lambda value: f"{value} 条",
            label_visibility="collapsed",
            width="stretch",
        )
    return start_index, end_index


def _render_feedback_detail_dialog(st, db_path, record: dict, similar_records: list[dict]) -> None:
    @st.dialog("反馈详情", width="large")
    def detail_dialog() -> None:
        repository = FeedbackRepository(db_path)
        action_repository = FeedbackActionRepository(db_path)
        feedback_id = int(record.get("id") or 0)
        priority = _priority(record)
        status = _status(record)
        notice = st.session_state.pop(f"feedback_reply_notice_{feedback_id}", None)
        if notice:
            st.success(str(notice))
        st.markdown(
            f"<div class='feedback-detail-head'><div>{_pill(CATEGORY_LABELS.get(str(record.get('category')), str(record.get('category') or '-')), 'info')}{_pill(PRIORITY_LABELS.get(priority, priority), _priority_tone(priority))}{_pill(STATUS_LABELS.get(status, status), 'neutral')}</div><div class='feedback-detail-title'>{escape(_short_text(record.get('content'), 96))}</div><div class='feedback-detail-meta'>{escape(_player(record))} · {escape(_server(record))} · {_compact_datetime(record.get('created_time'))}</div></div>",
            unsafe_allow_html=True,
        )
        content_tab, history_tab, similar_tab = st.tabs(["反馈内容", "处理记录", "相似反馈"])
        with content_tab:
            st.markdown(f"<div class='feedback-message'>{escape(str(record.get('content') or '暂无反馈内容'))}</div>", unsafe_allow_html=True)
            st.markdown(
                "<div class='feedback-grid'>"
                + "".join(
                    [
                        f"<div class='feedback-cell'><span>Discord 用户</span>{escape(str(record.get('discord_user_name') or record.get('discord_user_id') or '-'))}</div>",
                        f"<div class='feedback-cell'><span>频道</span>#{escape(_channel(record))}</div>",
                        f"<div class='feedback-cell'><span>帖子/区服</span>{escape(_server(record))}</div>",
                        f"<div class='feedback-cell'><span>AI 分类</span>{escape(CATEGORY_LABELS.get(str(record.get('category')), str(record.get('category') or '-')))}</div>",
                        f"<div class='feedback-cell'><span>情绪</span>{escape(str(record.get('sentiment') or '-'))}</div>",
                        f"<div class='feedback-cell'><span>置信度</span>基于规则归类</div>",
                    ]
                )
                + "</div>",
                unsafe_allow_html=True,
            )
        with history_tab:
            st.markdown(
                "<div class='feedback-grid'>"
                + "".join(
                    [
                        f"<div class='feedback-cell'><span>负责人</span>{escape(_owner(record))}</div>",
                        f"<div class='feedback-cell'><span>当前状态</span>{escape(STATUS_LABELS.get(status, status))}</div>",
                        f"<div class='feedback-cell'><span>最近更新</span>{escape(_compact_datetime(record.get('updated_time') or record.get('created_time')))}</div>",
                    ]
                )
                + "</div>",
                unsafe_allow_html=True,
            )
            action_rows = rows_to_records(action_repository.list_by_feedback(feedback_id))
            st.markdown(_feedback_history_html(action_rows), unsafe_allow_html=True)
        with similar_tab:
            if not similar_records:
                st.markdown("<div class='feedback-zero-state'>暂无相似反馈。</div>", unsafe_allow_html=True)
            else:
                for item in similar_records[:10]:
                    first = _compact_datetime(item.get("created_time"))
                    sim = SequenceMatcher(None, _similarity_key(record), _similarity_key(item)).ratio()
                    st.markdown(
                        f"<div class='feedback-topic-card'><div class='feedback-topic-title'>#{escape(str(item.get('id')))} · {escape(_short_text(item.get('content'), 80))}</div><div class='feedback-topic-meta'><span>玩家：{escape(_player(item))}</span><span>频道：{escape(_source_channel(item))}</span><span>首次/最近：{first}</span><span>相似度：{sim:.0%}</span></div></div>",
                        unsafe_allow_html=True,
                    )
        st.divider()
        reply_state_key = f"feedback_reply_open_{feedback_id}"
        reply_content_key = f"feedback_reply_content_{feedback_id}"
        action_cols = st.columns(4)
        if action_cols[0].button("忽略", key=f"ignore_feedback_{feedback_id}", width="stretch"):
            st.session_state[f"confirm_ignore_feedback_{feedback_id}"] = True
        if st.session_state.get(f"confirm_ignore_feedback_{feedback_id}"):
            if st.checkbox("确认忽略该反馈", key=f"ignore_checkbox_{feedback_id}"):
                repository.update_thread_status(feedback_id, "Ignored")
                _clear_feedback_caches(st)
                st.rerun()
        if action_cols[1].button("转为处理中", key=f"progress_feedback_{feedback_id}", width="stretch"):
            repository.update_thread_status(feedback_id, "In Progress")
            _clear_feedback_caches(st)
            st.rerun()
        if action_cols[2].button("回复帖子", key=f"reply_feedback_{feedback_id}", type="primary", width="stretch"):
            st.session_state[reply_state_key] = True
        if action_cols[3].button("标记已解决", key=f"resolve_feedback_{feedback_id}", width="stretch"):
            repository.update_thread_status(feedback_id, "Resolved")
            _clear_feedback_caches(st)
            st.rerun()

        if st.session_state.get(reply_state_key, False):
            thread_title = str(record.get("thread_title") or "").strip()
            destination_label = "当前帖子" if thread_title else "来源频道"
            with st.form(f"feedback_reply_form_{feedback_id}", border=True):
                st.markdown(f"#### 通过 Discord Bot 回复{destination_label}")
                if thread_title:
                    st.caption(
                        f"消息将由 Bot 直接发送到帖子“{thread_title}”下方；"
                        "不会私信玩家，发送后也不会自动改变反馈状态。"
                    )
                else:
                    st.caption(
                        f"消息将由 Bot 直接发送到来源频道 #{_channel(record)}；"
                        "不会私信玩家，发送后也不会自动改变反馈状态。"
                    )
                reply_content = st.text_area(
                    "回复内容",
                    key=reply_content_key,
                    height=120,
                    placeholder=f"输入要发送到{destination_label}的回复…",
                )
                send_col, cancel_col = st.columns([1, 1])
                send_reply = send_col.form_submit_button(
                    f"发送到{destination_label}",
                    type="primary",
                    width="stretch",
                )
                cancel_reply = cancel_col.form_submit_button("取消", width="stretch")

                if send_reply:
                    try:
                        with st.spinner(f"正在通过 Discord Bot 回复{destination_label}…"):
                            result = FeedbackReplyService(db_path).reply_to_feedback(
                                str(record.get("channel_id") or ""),
                                thread_title or None,
                                reply_content,
                                feedback_id=feedback_id,
                            )
                    except (RuntimeError, ValueError) as exc:
                        st.error(f"发送失败：{exc}")
                    else:
                        st.session_state[reply_state_key] = False
                        st.session_state[f"feedback_reply_notice_{feedback_id}"] = (
                            f"已通过 Discord Bot 回复{destination_label}。"
                            f"处理记录已保存，消息 ID：{result.discord_message_id}"
                        )
                        st.session_state["feedback_detail_id"] = feedback_id
                        _clear_feedback_caches(st)
                        st.rerun()

                if cancel_reply:
                    st.session_state[reply_state_key] = False
                    st.rerun()

    detail_dialog()


def _feedback_history_html(action_rows: list[dict]) -> str:
    if not action_rows:
        return (
            "<div class='feedback-zero-state'>暂未产生处理记录。"
            "通过 Bot 回复帖子后会自动记录在这里。</div>"
        )

    items: list[str] = []
    for action in action_rows:
        action_type = str(action.get("action_type") or "")
        action_label = "Bot 回复帖子" if action_type == "BOT_REPLY" else "反馈处理"
        destination = str(action.get("destination_label") or "来源频道")
        channel_id = str(action.get("discord_channel_id") or "-")
        message_id = str(action.get("discord_message_id") or "-")
        items.append(
            "<div class='feedback-history-item'>"
            f"<div><div class='feedback-history-kind'>{escape(action_label)}</div>"
            f"<div class='feedback-history-time'>{escape(_compact_datetime(action.get('created_time')))}</div></div>"
            f"<div><div class='feedback-history-content'>{escape(str(action.get('content') or '-'))}</div>"
            "<div class='feedback-history-meta'>"
            f"<span>目标：{escape(destination)}</span>"
            f"<span>频道 ID：{escape(channel_id)}</span>"
            f"<span>消息 ID：{escape(message_id)}</span>"
            "</div></div></div>"
        )
    return (
        "<div class='feedback-history'>"
        f"<div class='feedback-history-head'><span>处理流水</span><span class='feedback-history-count'>{len(action_rows)} 条</span></div>"
        + "".join(items)
        + "</div>"
    )


def _pill(label: str, tone: str = "neutral") -> str:
    return f'<span class="status-pill {tone}">{escape(label)}</span>'


def _priority_tone(priority: str) -> str:
    if priority == "High":
        return "danger"
    if priority == "Medium":
        return "warning"
    return "neutral"


def _render_queue(st, db_path) -> None:
    start_date, end_date, category, priority, status_filter, keyword, merge_similar = _render_filters(st)
    if start_date > end_date:
        st.warning("开始日期不能晚于结束日期。")
        return
    start_time, end_time = date_range_to_datetimes(start_date, end_date)
    rows = _cached_feedback_rows(st, db_path, start_time, end_time, category, priority, status_filter, 1000)
    rows = _collapse_thread_feedback(rows)
    rows = _filter_keyword(rows, keyword)
    groups = _similar_groups(rows)
    if merge_similar:
        rows = _dedupe_similar(rows)
    records_by_id = {int(row.get("id") or 0): row for row in rows}
    table_rows = _queue_table_records(rows, groups)
    with st.container(key="feedback_queue_panel"):
        _render_queue_header(st, len(rows), rows, groups)
        if not table_rows:
            st.markdown("<div class='feedback-zero-state'>当前筛选条件下暂无玩家反馈。可以清除筛选或扩大日期范围。</div>", unsafe_allow_html=True)
            return
        start_index, end_index = _pagination_controls(st, len(rows))
        page_rows = rows[start_index:end_index]
        _render_feedback_workspace(st, db_path, page_rows, groups)
    detail_request = _consume_dialog_request(st, "feedback_detail_id")
    if detail_request is not None:
        detail_id = int(detail_request)
        selected = records_by_id.get(detail_id) or next((row for row in rows if int(row.get("id") or 0) == detail_id), None)
        if selected:
            _render_feedback_detail_dialog(st, db_path, selected, groups.get(detail_id, []))


STOPWORDS = {
    "same", "type", "just", "different", "scenario", "scenio", "with", "from", "that", "this",
    "there", "their", "about", "would", "could", "should", "have", "has", "had", "been", "being",
    "were", "was", "are", "is", "am", "the", "and", "for", "you", "your", "our", "can", "cant",
    "cannot", "not", "but", "all", "any", "some", "more", "less", "very", "please", "need",
    "needs", "fix", "make", "get", "got", "when", "where", "what", "why", "how", "into", "onto",
    "of", "in", "on", "to", "a", "an", "it", "as", "at", "by", "or", "be", "do", "does", "did",
}


def _insight_range_days(st) -> int:
    st.session_state.setdefault("feedback_insight_range", "近14天")
    label = st.segmented_control(
        "洞察范围",
        options=("近7天", "近14天", "近30天"),
        key="feedback_insight_range",
    )
    return {"近7天": 7, "近14天": 14, "近30天": 30}[label]


def _records_in_days(st, db_path, days: int) -> list[dict]:
    today = date.today()
    start_time, end_time = date_range_to_datetimes(today - timedelta(days=days - 1), today)
    return _cached_feedback_rows(st, db_path, start_time, end_time, "All", "All", "All", 1000)


def _trend_frame(records: list[dict], days: int) -> pd.DataFrame:
    today = date.today()
    rows = []
    for offset in range(days):
        current = today - timedelta(days=days - offset - 1)
        day_records = [record for record in records if (_parse_datetime(record.get("created_time")) or datetime.min).date() == current]
        rows.append({"日期": current.isoformat(), "日期标签": f"{current.month}/{current.day}", "指标": "新增反馈", "数量": len(day_records)})
        rows.append({"日期": current.isoformat(), "日期标签": f"{current.month}/{current.day}", "指标": "已解决反馈", "数量": sum(1 for record in day_records if _status(record) == "Resolved")})
        rows.append({"日期": current.isoformat(), "日期标签": f"{current.month}/{current.day}", "指标": "高优先级新增", "数量": sum(1 for record in day_records if _priority(record) == "High")})
    return pd.DataFrame(rows)


def _valid_keywords(content: object) -> list[str]:
    words = normalize_feedback_content(str(content or "")).split()
    return [
        word
        for word in words
        if len(word) >= 4
        and word not in STOPWORDS
        and not word.isdigit()
        and not all(char in "-_." for char in word)
    ]


def _issue_theme(record: dict) -> str:
    content = str(record.get("content") or "")
    normalized = normalize_feedback_content(content)
    if "bug" in normalized and ("same" in normalized or "different" in normalized or "scenario" in normalized or "scenio" in normalized):
        return "同类BUG在不同场景重复出现"
    if record.get("thread_title"):
        return str(record.get("thread_title"))
    keywords = _valid_keywords(content)
    if keywords:
        return " / ".join(keywords[:3])
    return _short_text(content, 36)


def _high_frequency_issues(records: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        theme = _issue_theme(record)
        if not theme or theme == "-":
            continue
        buckets[theme].append(record)
    rows = []
    for theme, items in buckets.items():
        if len(items) < 1:
            continue
        latest = max((_parse_datetime(item.get("created_time")) or datetime.min) for item in items)
        players = {str(item.get("discord_user_id") or "") for item in items}
        statuses = Counter(_status(item) for item in items)
        main_status = statuses.most_common(1)[0][0] if statuses else "Open"
        rows.append(
            {
                "问题主题": theme,
                "反馈数": len(items),
                "涉及玩家": len(players),
                "最近反馈时间": latest.strftime("%Y/%m/%d %H:%M") if latest != datetime.min else "暂无数据",
                "处理状态": STATUS_LABELS.get(main_status, main_status),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["反馈数"]), str(row["最近反馈时间"])))[:8]


def _current_pending_count(db_path) -> int:
    repository = FeedbackRepository(db_path)
    return repository.count_by_status("Open") + repository.count_by_status("In Progress")


def _longest_pending_text(db_path) -> str:
    open_rows = rows_to_records(FeedbackRepository(db_path).list_open())
    open_times = [_parse_datetime(row.get("created_time")) for row in open_rows]
    open_times = [value for value in open_times if value]
    if not open_times:
        return "暂无数据"
    hours = int((datetime.now() - min(open_times)).total_seconds() // 3600)
    if hours < 24:
        return f"{hours}小时"
    return f"{hours // 24}天{hours % 24}小时"


def _insight_metric_cards(st, records: list[dict], days: int, pending_count: int) -> None:
    new_count = len(records)
    resolved_count = sum(1 for record in records if _status(record) == "Resolved")
    denominator = max(new_count, resolved_count)
    resolve_rate = resolved_count / denominator if denominator else 0
    metrics = [
        (f"近{days}日新增", str(new_count), "反馈采集数量"),
        (f"近{days}日已解决", str(resolved_count), "状态为已解决"),
        ("当前待处理", str(pending_count), "Open + In Progress"),
        ("解决率", f"{resolve_rate:.0%}", f"{resolved_count}/{denominator}"),
        ("平均处理时长", "暂无数据", "？"),
    ]
    st.markdown(
        "<div class='feedback-insight-metrics'>"
        + "".join(
            f"<div class='feedback-insight-metric'><div class='feedback-insight-metric-label'>{escape(label)}</div><div class='feedback-insight-metric-value'>{escape(value)}</div><div class='feedback-insight-metric-help' title='平均处理时长需要记录首次响应与解决完成时间后计算'>{escape(help_text)}</div></div>"
            for label, value, help_text in metrics
        )
        + "</div>",
        unsafe_allow_html=True,
    )


def _render_trend_chart(st, records: list[dict], days: int, pending_count: int) -> None:
    trend_df = _trend_frame(records, days)
    total = int(trend_df["数量"].sum()) if not trend_df.empty else 0
    new_count = sum(1 for row in trend_df.to_dict("records") if row["指标"] == "新增反馈" for _ in range(int(row["数量"])))
    resolved_count = sum(1 for row in trend_df.to_dict("records") if row["指标"] == "已解决反馈" for _ in range(int(row["数量"])))
    st.markdown(
        f"<div class='feedback-insight-card'><div class='feedback-insight-head'><div><div class='feedback-insight-title'>每日反馈与解决趋势</div><div class='feedback-insight-subtitle'>近{days}日新增{new_count}条，已解决{resolved_count}条，当前待处理{pending_count}条。</div></div></div>",
        unsafe_allow_html=True,
    )
    if total == 0:
        st.markdown(f"<div class='feedback-zero-state'>近{days}日暂无反馈变化，社区反馈状态稳定。</div></div>", unsafe_allow_html=True)
        return

    bars = (
        alt.Chart(trend_df)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("日期标签:N", title=None, axis=alt.Axis(labelAngle=0), sort=list(trend_df["日期标签"].drop_duplicates())),
            xOffset=alt.XOffset("指标:N"),
            y=alt.Y("数量:Q", title=None, axis=alt.Axis(tickMinStep=1, gridColor="#E9EDF3")),
            color=alt.Color("指标:N", title=None, scale=alt.Scale(domain=["新增反馈", "已解决反馈", "高优先级新增"], range=["#3B82F6", "#22C55E", "#EF4444"])),
            tooltip=[alt.Tooltip("日期:N", title="日期"), alt.Tooltip("指标:N", title="指标"), alt.Tooltip("数量:Q", title="数量", format="d")],
        )
    )
    labels = (
        alt.Chart(trend_df[trend_df["数量"] > 0])
        .mark_text(dy=-6, fontSize=11, color="#1D1D1F")
        .encode(
            x=alt.X("日期标签:N", sort=list(trend_df["日期标签"].drop_duplicates())),
            xOffset=alt.XOffset("指标:N"),
            y=alt.Y("数量:Q"),
            text=alt.Text("数量:Q", format="d"),
        )
    )
    chart = (bars + labels).properties(height=250).configure_view(strokeWidth=0)
    st.altair_chart(chart, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_category_chart(st, records: list[dict]) -> None:
    counts = Counter(CATEGORY_LABELS.get(str(record.get("category")), str(record.get("category") or "-")) for record in records)
    total = sum(counts.values())
    st.markdown("<div class='feedback-insight-card'><div class='feedback-insight-title'>分类分布</div><div class='feedback-insight-subtitle'>按数量从高到低排列，点击分类可同步筛选待处理队列。</div>", unsafe_allow_html=True)
    if total == 0:
        st.markdown("<div class='feedback-zero-state'>暂无分类数据。</div></div>", unsafe_allow_html=True)
        return
    category_df = pd.DataFrame(
        [
            {"分类": key, "数量": value, "占比": value / total, "标签": f"{key} {value}条 · {value / total:.0%}"}
            for key, value in counts.most_common()
        ]
    )
    if len(category_df) == 1:
        row = category_df.iloc[0]
        st.markdown(f"<div class='feedback-topic-card'><div class='feedback-topic-title'>{escape(str(row['标签']))}</div><div class='feedback-topic-meta'><span>当前范围内仅识别出一个反馈分类</span></div></div></div>", unsafe_allow_html=True)
        return
    chart = (
        alt.Chart(category_df)
        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
        .encode(
            y=alt.Y("分类:N", title=None, sort="-x"),
            x=alt.X("数量:Q", title=None, axis=alt.Axis(tickMinStep=1, gridColor="#E9EDF3")),
            color=alt.value("#8A94A3"),
            tooltip=[alt.Tooltip("分类:N", title="分类"), alt.Tooltip("数量:Q", title="数量", format="d"), alt.Tooltip("占比:Q", title="占比", format=".0%")],
        )
        .properties(height=250)
    )
    labels = (
        alt.Chart(category_df)
        .mark_text(align="left", dx=6, fontSize=12, color="#1D1D1F")
        .encode(y=alt.Y("分类:N", sort="-x"), x="数量:Q", text="标签:N")
    )
    st.altair_chart((chart + labels).configure_view(strokeWidth=0), use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_high_frequency_issues(st, records: list[dict]) -> None:
    issues = _high_frequency_issues(records)
    st.markdown("<div class='feedback-insight-card'><div class='feedback-insight-title'>高频问题</div><div class='feedback-insight-subtitle'>过滤普通虚词后，按相似内容归纳可处理的问题主题。</div>", unsafe_allow_html=True)
    if not issues:
        st.markdown("<div class='feedback-zero-state'>暂未识别出高频问题。</div></div>", unsafe_allow_html=True)
        return
    st.markdown("<div class='feedback-topic-table'><div class='feedback-topic-header'><div>问题主题</div><div>反馈数</div><div>涉及玩家</div><div>最近反馈时间</div><div>处理状态</div></div>", unsafe_allow_html=True)
    for issue in issues:
        st.markdown(
            f"<div class='feedback-topic-row'><div>{escape(str(issue['问题主题']))}</div><div>{issue['反馈数']}</div><div>{issue['涉及玩家']}</div><div>{escape(str(issue['最近反馈时间']))}</div><div>{escape(str(issue['处理状态']))}</div></div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div></div>", unsafe_allow_html=True)


def _render_efficiency(st, records: list[dict], db_path) -> None:
    resolved = sum(1 for record in records if _status(record) == "Resolved")
    denominator = max(len(records), resolved)
    overdue = sum(1 for record in records if _is_overdue(record))
    metrics = [
        ("平均首次响应时间", "暂无数据", "等待接入首次处理时间", "需要记录首次人工处理或首次回复时间后计算"),
        ("平均解决时间", "暂无数据", "等待接入解决完成时间", "需要记录反馈解决完成时间后计算"),
        ("超时反馈数", str(overdue), "超过 SLA 且仍未解决", "按当前优先级对应的 SLA 阈值计算"),
        ("解决率", f"{(resolved / denominator if denominator else 0):.0%}", f"{resolved}/{denominator}", "已解决反馈数 / 当前范围反馈数"),
        ("最久待处理时间", _longest_pending_text(db_path), "基于未解决反馈创建时间", "当前仍处于待处理或处理中状态的最早反馈"),
    ]
    st.markdown(
        "<div class='feedback-insight-card'><div class='feedback-insight-title'>处理效率</div><div class='feedback-insight-subtitle'>暂无数据的指标会在接入处理时间来源后自动可计算。</div><div class='feedback-insight-metrics'>"
        + "".join(
            f"<div class='feedback-insight-metric'><div class='feedback-insight-metric-label'>{escape(label)} <span title='{escape(tip)}'>?</span></div><div class='feedback-insight-metric-value'>{escape(value)}</div><div class='feedback-insight-metric-help'>{escape(helper)}</div></div>"
            for label, value, helper, tip in metrics
        )
        + "</div></div>",
        unsafe_allow_html=True,
    )


def _render_insights(st, db_path) -> None:
    today = date.today()
    header_cols = st.columns([4, 1])
    header_cols[0].markdown("<div class='feedback-section-title'>数据洞察</div><div class='feedback-section-caption'>查看处理概览、反馈趋势、分类分布、高频问题和处理效率。</div>", unsafe_allow_html=True)
    if header_cols[1].button("日历视图", use_container_width=True):
        st.session_state["feedback_calendar_open"] = True
    if _consume_dialog_request(st, "feedback_calendar_open"):
        _render_calendar_dialog(st, db_path)
    days = _insight_range_days(st)
    records = _records_in_days(st, db_path, days)
    pending_count = _current_pending_count(db_path)
    _insight_metric_cards(st, records, days, pending_count)
    if not records:
        st.markdown(f"<div class='feedback-zero-state'>近{days}日暂无反馈数据，社区反馈状态稳定。</div>", unsafe_allow_html=True)
        return
    chart_cols = st.columns([0.65, 0.35])
    with chart_cols[0]:
        _render_trend_chart(st, records, days, pending_count)
    with chart_cols[1]:
        _render_category_chart(st, records)
    _render_high_frequency_issues(st, records)
    _render_efficiency(st, records, db_path)


def render(st, db_path) -> None:
    _feedback_css(st)
    repository = FeedbackRepository(db_path)
    today = date.today()
    st.session_state.setdefault("feedback_start_date", today)
    st.session_state.setdefault("feedback_end_date", today)
    _overview(st, repository, db_path)
    _render_queue(st, db_path)
