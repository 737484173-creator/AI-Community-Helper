from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from html import escape

import pandas as pd

from app.dashboard.export_utils import records_to_csv
from app.dashboard.formatters import rows_to_records
from app.database.repositories.discord_channel_repository import DiscordChannelRepository
from app.database.repositories.event_analytics_repository import EventAnalyticsRepository
from app.database.repositories.event_repository import EventRepository
from app.event_assets import (
    EventImageValidationError,
    delete_event_image,
    save_event_image,
    validate_event_image,
)
from app.scheduler.event_options import options_to_json, parse_event_options
from app.utils.time_utils import format_datetime, parse_datetime


EVENT_TYPES = ("Poll", "Survey", "Announcement", "Quiz")
EVENT_TYPES_WITH_OPTIONS = frozenset({"Poll", "Survey", "Quiz"})
EVENT_STATUSES = ("Draft", "Scheduled")
EVENT_STATUS_FILTERS = ("All", "Draft", "Scheduled", "Published", "Cancelled", "Completed")
EVENT_TYPE_LABELS = {
    "All": "全部",
    "Poll": "投票",
    "Survey": "调查",
    "Announcement": "公告",
    "Quiz": "问答",
}
EVENT_STATUS_LABELS = {
    "All": "全部",
    "Draft": "草稿",
    "Scheduled": "已排期",
    "Published": "已发布",
    "Cancelled": "已取消",
    "Completed": "已完成",
}

EVENT_STATUS_TONES = {
    "Draft": "neutral",
    "Scheduled": "warning",
    "Published": "success",
    "Cancelled": "neutral",
    "Completed": "info",
}

EVENT_TYPE_TONES = {
    "Poll": "info",
    "Survey": "neutral",
    "Announcement": "success",
    "Quiz": "warning",
}

EVENT_CACHE_REVISION_KEY = "_event_management_cache_revision"


def _event_options_json(event_type: str, raw_options: str | None) -> str | None:
    """Return serialized choices only for event types that support them."""
    if event_type not in EVENT_TYPES_WITH_OPTIONS:
        return None
    return options_to_json(parse_event_options(raw_options))


def _render_event_management_css(st) -> None:
    st.markdown(
        """
        <style>
        .event-overview-band {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            margin-top: 6px;
            overflow: hidden;
            border-top: 1px solid var(--border-strong);
            border-bottom: 1px solid var(--border);
            background: color-mix(in srgb, var(--surface-muted) 52%, transparent);
        }
        .event-overview-item {
            min-width: 0;
            padding: 16px 18px;
        }
        .event-overview-item + .event-overview-item {
            border-left: 1px solid var(--border);
        }
        .event-overview-label {
            color: var(--text-secondary);
            font-size: 12px;
            font-weight: 650;
        }
        .event-overview-value {
            margin: 5px 0 6px;
            color: var(--text-primary);
            font-size: 28px;
            font-weight: 720;
            font-variant-numeric: tabular-nums;
            line-height: 1;
            letter-spacing: -.035em;
        }
        .event-overview-note {
            color: var(--text-tertiary);
            font-size: 12px;
            line-height: 1.45;
            text-wrap: pretty;
        }
        .activity-effect-summary {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
        }
        .activity-effect-summary .event-effect-summary-item {
            min-width: 0;
        }
        .activity-effect-summary .event-effect-value.compact {
            font-size: 13px;
            line-height: 1.45;
            letter-spacing: 0;
            overflow-wrap: anywhere;
        }
        .event-branch-heading {
            display: flex;
            align-items: center;
            gap: 10px;
            margin: 14px 0 10px;
            color: var(--text-primary);
            font-size: 13px;
            font-weight: 680;
        }
        .event-branch-heading::after {
            flex: 1;
            height: 1px;
            background: var(--border);
            content: "";
        }
        .event-branch-meta {
            margin-bottom: 10px;
            color: var(--text-secondary);
            font-size: 12px;
            line-height: 1.5;
            text-wrap: pretty;
        }
        .event-archive-overview {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 14px;
            min-height: 38px;
            padding: 8px 12px;
            margin: 14px 0 12px;
            color: var(--text-secondary);
            border: 1px solid var(--border);
            border-radius: var(--radius-control);
            background: var(--surface-muted);
            font-size: 12px;
            line-height: 1.5;
        }
        .event-archive-overview strong {
            color: var(--text-primary);
            font-weight: 680;
            text-align: right;
        }
        div.stVerticalBlock.st-key-event_effect_archive_tree { gap: 10px; }
        [class*="st-key-event_effect_week_"] > details {
            border-color: var(--border-strong) !important;
        }
        [class*="st-key-event_effect_week_"] > details > summary {
            min-height: 50px !important;
            padding-inline: 16px !important;
            font-size: 15px;
        }
        [class*="st-key-event_effect_week_"] > details[open] > summary {
            border-bottom: 1px solid var(--border);
            background: color-mix(in srgb, var(--primary-soft) 42%, var(--surface));
        }
        [class*="st-key-event_effect_week_"] > details > div {
            padding: 12px 14px 14px !important;
        }
        [class*="st-key-event_effect_day_"] > details {
            border-color: color-mix(in srgb, var(--border-strong) 72%, transparent) !important;
            background: color-mix(in srgb, var(--surface-muted) 74%, var(--surface)) !important;
        }
        [class*="st-key-event_effect_day_"] > details > summary {
            min-height: 44px !important;
            font-size: 13px;
        }
        [class*="st-key-event_effect_day_"] > details[open] > summary {
            border-bottom: 1px solid var(--border);
            background: var(--surface-muted);
        }
        [class*="st-key-event_effect_day_"] > details > div { padding: 8px !important; }
        div.stVerticalBlock.st-key-event_image_preview {
            gap: 12px;
            padding: 12px;
            border: 1px solid var(--border);
            border-radius: var(--radius-control);
            background: color-mix(in srgb, var(--surface-muted) 58%, var(--surface));
        }
        div.stVerticalBlock.st-key-event_image_preview [data-testid="stImage"] img {
            width: 100%;
            max-height: 220px;
            object-fit: contain;
            border-radius: calc(var(--radius-control) - 2px);
            background: var(--surface);
        }
        @media (max-width: 760px) {
            .event-overview-band { grid-template-columns: 1fr; }
            .event-overview-item + .event-overview-item {
                border-top: 1px solid var(--border);
                border-left: 0;
            }
            .activity-effect-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .event-archive-overview {
                align-items: flex-start;
                flex-direction: column;
                gap: 3px;
            }
            .event-archive-overview strong { text-align: left; }
            [class*="st-key-event_effect_week_"] > details > div { padding-inline: 8px !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _cached_publishable_channels(st, db_path) -> list[dict]:
    @st.cache_data(ttl=30, show_spinner=False)
    def _load(
        path: str,
        cache_revision: int,
    ) -> list[dict]:
        return rows_to_records(DiscordChannelRepository(path).list_publishable())

    return _load(
        str(db_path),
        _event_cache_revision(st),
    )


def _cached_event_rows(st, db_path, status: str, event_type: str) -> list[dict]:
    @st.cache_data(ttl=15, show_spinner=False)
    def _load(
        path: str,
        selected_status: str,
        selected_event_type: str,
        cache_revision: int,
    ) -> list[dict]:
        return rows_to_records(
            EventRepository(path).list_filtered(
                status=selected_status,
                event_type=selected_event_type,
            )
        )

    return _load(
        str(db_path),
        status,
        event_type,
        _event_cache_revision(st),
    )


def _cached_analytics_rows(st, db_path, limit: int = 100) -> list[dict]:
    @st.cache_data(ttl=15, show_spinner=False)
    def _load(
        path: str,
        row_limit: int,
        cache_revision: int,
    ) -> list[dict]:
        return rows_to_records(EventAnalyticsRepository(path).list_recent_with_events(row_limit))

    return _load(
        str(db_path),
        limit,
        _event_cache_revision(st),
    )


def _event_cache_revision(st) -> int:
    return int(st.session_state.setdefault(EVENT_CACHE_REVISION_KEY, 0))


def _clear_event_caches(st) -> None:
    st.session_state[EVENT_CACHE_REVISION_KEY] = _event_cache_revision(st) + 1


def _channel_label(channel: dict) -> str:
    channel_name = str(channel["channel_name"])
    channel_type = str(channel.get("channel_type") or "Channel")
    prefix = "#" if channel_type in {"TextChannel", "ForumChannel"} else ""
    return f"{prefix}{channel_name}"


def _format_event_rows(records: list[dict], channel_lookup: dict[str, str]) -> list[dict]:
    formatted = []
    now = datetime.now()
    for record in records:
        channel_id = str(record.get("channel_id") or "")
        event_type = str(record.get("event_type") or "")
        status = str(record.get("status") or "")
        formatted.append(
            {
                "ID": record.get("id"),
                "活动标题": record.get("title"),
                "类型": EVENT_TYPE_LABELS.get(event_type, event_type),
                "状态": EVENT_STATUS_LABELS.get(status, status),
                "发布频道": channel_lookup.get(channel_id, channel_id),
                "发布时间": record.get("publish_time"),
                "Discord 发布状态": _discord_publish_status(record, now),
            }
        )
    return formatted


def _event_status_counts(records: list[dict]) -> dict[str, int]:
    counts = {status: 0 for status in EVENT_STATUS_FILTERS if status != "All"}
    for record in records:
        status = str(record.get("status") or "")
        if status in counts:
            counts[status] += 1
    return counts


def _status_pill(label: str, value: int | str, tone: str = "neutral") -> str:
    return (
        f'<span class="status-pill {escape(tone)}">'
        f"{escape(label)}：{escape(str(value))}</span>"
    )


def _render_event_status_strip(st, records: list[dict]) -> None:
    counts = _event_status_counts(records)
    pills = [
        _status_pill("全部", len(records), "info"),
        *[
            _status_pill(
                EVENT_STATUS_LABELS[status],
                count,
                EVENT_STATUS_TONES.get(status, "neutral"),
            )
            for status, count in counts.items()
            if count
        ],
    ]
    st.markdown(
        '<div class="status-row">' + "".join(pills) + "</div>",
        unsafe_allow_html=True,
    )


def _discord_publish_status(record: dict, now: datetime) -> str:
    if record.get("discord_message_id"):
        return f"已发布到 Discord：{record['discord_message_id']}"
    if record.get("status") != "Scheduled":
        return "未排期发布"

    try:
        publish_time = parse_datetime(str(record.get("publish_time")))
    except ValueError:
        return "发布时间格式异常，Bot 无法判断是否到期"

    if publish_time > now:
        return "等待发布时间"
    return "已到发布时间，等待 Discord Bot 在线发布"


def _poll_option_results(poll_result_json: str | None) -> list[dict]:
    if not poll_result_json:
        return []
    try:
        data = json.loads(poll_result_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []

    option_results = data.get("option_results")
    if not isinstance(option_results, list):
        return []

    results: list[dict] = []
    for item in option_results:
        if not isinstance(item, dict):
            continue
        try:
            count = int(item.get("count", 0) or 0)
        except (TypeError, ValueError):
            count = 0
        option = str(item.get("option") or "")
        if option.startswith("[") and option.endswith("]"):
            try:
                decoded = json.loads(option)
                if isinstance(decoded, list) and decoded:
                    option = str(decoded[0])
            except json.JSONDecodeError:
                option = option.strip("[]\"'")
        results.append(
            {
                "marker": str(item.get("marker") or ""),
                "option": option,
                "count": count,
            }
        )
    return results


def _poll_winner_label(option_results: list[dict]) -> str:
    if not option_results:
        return "暂无"
    winner = max(option_results, key=lambda item: int(item.get("count", 0) or 0))
    if int(winner.get("count", 0) or 0) <= 0:
        return "暂无投票"
    return f"{winner['marker']}. {winner['option']} ({winner['count']} 票)"


def _poll_total_votes(option_results: list[dict]) -> int:
    return sum(int(item.get("count", 0) or 0) for item in option_results)


def _format_analytics_summary_rows(
    records: list[dict],
    channel_lookup: dict[str, str],
) -> list[dict]:
    formatted: list[dict] = []
    for record in records:
        option_results = _poll_option_results(record.get("poll_result_json"))
        channel_id = str(record.get("channel_id") or "")
        formatted.append(
            {
                "活动 ID": record.get("event_id"),
                "活动标题": record.get("title"),
                "活动类型": EVENT_TYPE_LABELS.get(
                    str(record.get("event_type") or ""),
                    record.get("event_type"),
                ),
                "发布频道": channel_lookup.get(channel_id, channel_id),
                "发布时间": record.get("published_time"),
                "参与人数": record.get("participant_count"),
                "互动数": record.get("reaction_count"),
                "当前领先": _poll_winner_label(option_results),
            }
        )
    return formatted


def _event_analytics_overview(records: list[dict]) -> dict[str, int]:
    return {
        "活动数": len(
            {
                int(row.get("event_id") or 0)
                for row in records
                if row.get("event_id") not in (None, "")
            }
        ),
        "参与人数": sum(int(row.get("participant_count") or 0) for row in records),
        "互动数": sum(int(row.get("reaction_count") or 0) for row in records),
    }


def _overdue_scheduled_events(
    records: list[dict],
    now: datetime | None = None,
    grace_seconds: int = 60,
) -> list[dict]:
    cutoff = (now or datetime.now()) - timedelta(seconds=grace_seconds)
    overdue: list[dict] = []
    for record in records:
        if record.get("status") != "Scheduled" or record.get("discord_message_id"):
            continue
        try:
            publish_time = parse_datetime(str(record.get("publish_time") or ""))
        except ValueError:
            continue
        if publish_time <= cutoff:
            overdue.append(record)
    return overdue


def _analytics_filter_options(analytics_rows: list[dict]) -> list[tuple[str, int | None]]:
    options: list[tuple[str, int | None]] = [("全部活动", None)]
    seen_event_ids: set[int] = set()
    for row in analytics_rows:
        try:
            event_id = int(row.get("event_id"))
        except (TypeError, ValueError):
            continue
        if event_id in seen_event_ids:
            continue
        seen_event_ids.add(event_id)
        title = str(row.get("title") or "未命名活动")
        published_time = str(row.get("published_time") or "未记录发布时间")
        options.append((f"#{event_id} · {title} · {published_time}", event_id))
    return options


def _filter_analytics_rows(
    analytics_rows: list[dict],
    selected_event_id: int | None,
) -> list[dict]:
    if selected_event_id is None:
        return analytics_rows
    return [
        row
        for row in analytics_rows
        if int(row.get("event_id") or 0) == selected_event_id
    ]


def _event_effect_archive_date(record: dict) -> date:
    for field_name in ("published_time", "created_time", "updated_time"):
        value = record.get(field_name)
        if not value:
            continue
        try:
            return parse_datetime(str(value)).date()
        except ValueError:
            continue
    return date.min


def _event_effect_sort_id(record: dict) -> int:
    for field_name in ("id", "event_id"):
        try:
            return int(record.get(field_name) or 0)
        except (TypeError, ValueError):
            continue
    return 0


def _group_event_effects_by_week_day(
    records: list[dict],
) -> dict[date, dict[date, list[dict]]]:
    grouped: dict[date, dict[date, list[dict]]] = {}
    ordered = sorted(
        records,
        key=lambda record: (_event_effect_archive_date(record), _event_effect_sort_id(record)),
        reverse=True,
    )
    for record in ordered:
        archive_date = _event_effect_archive_date(record)
        week_start = archive_date - timedelta(days=archive_date.weekday())
        grouped.setdefault(week_start, {}).setdefault(archive_date, []).append(record)
    return grouped


def _event_effect_count(records: list[dict]) -> int:
    event_ids = {
        str(record.get("event_id"))
        for record in records
        if record.get("event_id") not in (None, "")
    }
    missing_id_count = sum(
        1 for record in records if record.get("event_id") in (None, "")
    )
    return len(event_ids) + missing_id_count


def _event_week_archive_label(week_start: date, records: list[dict]) -> str:
    iso_year, iso_week, _ = week_start.isocalendar()
    week_end = week_start + timedelta(days=6)
    return (
        f"{iso_year} 年第 {iso_week:02d} 周 · "
        f"{week_start:%m/%d}–{week_end:%m/%d} · {_event_effect_count(records)} 个活动"
    )


def _event_day_archive_label(archive_date: date, records: list[dict]) -> str:
    overview = _event_analytics_overview(records)
    return (
        f"{archive_date:%m 月 %d 日} · {overview['活动数']} 个活动 · "
        f"参与 {overview['参与人数']:,} · 互动 {overview['互动数']:,}"
    )


def _render_event_overview(st, overview: dict[str, int]) -> None:
    items = (
        ("活动数", overview["活动数"], "当前筛选范围内的活动"),
        ("参与人数", overview["参与人数"], "参与投票或互动的去重用户"),
        ("消息互动", overview["互动数"], "活动消息收到的投票与表情互动总量"),
    )
    cards = "".join(
        '<div class="event-overview-item">'
        f'<div class="event-overview-label">{escape(label)}</div>'
        f'<div class="event-overview-value">{value:,}</div>'
        f'<div class="event-overview-note">{escape(note)}</div>'
        "</div>"
        for label, value, note in items
    )
    st.markdown(f'<div class="event-overview-band">{cards}</div>', unsafe_allow_html=True)


def _render_event_effect_cards(
    st,
    analytics_rows: list[dict],
    event_status_lookup: dict[int, dict] | None = None,
) -> None:
    event_status_lookup = event_status_lookup or {}
    for row in analytics_rows:
        option_results = _poll_option_results(row.get("poll_result_json"))
        total_votes = _poll_total_votes(option_results)
        participant_count = int(row.get("participant_count") or 0)
        interaction_count = int(row.get("reaction_count") or 0)
        winner_label = _poll_winner_label(option_results)
        event_id = int(row.get("event_id") or 0)
        event_status = event_status_lookup.get(event_id, {})
        publish_status = str(event_status.get("Discord 发布状态") or "暂无发布状态")
        event_type = EVENT_TYPE_LABELS.get(
            str(row.get("event_type") or ""),
            str(row.get("event_type") or "未分类"),
        )
        expander_label = (
            f"#{row.get('event_id')} · {row.get('title') or '未命名活动'} · "
            f"参与 {participant_count} · 互动 {interaction_count} · {publish_status}"
        )
        with st.expander(expander_label, expanded=False):
            st.markdown(
                f"""
                <div class="event-effect-card drawer">
                    <div class="activity-effect-summary">
                        <div class="event-effect-summary-item">
                            <div class="event-effect-label">参与人数</div>
                            <div class="event-effect-value">{participant_count}</div>
                        </div>
                        <div class="event-effect-summary-item">
                            <div class="event-effect-label">消息互动</div>
                            <div class="event-effect-value">{interaction_count}</div>
                        </div>
                        <div class="event-effect-summary-item">
                            <div class="event-effect-label">活动类型</div>
                            <div class="event-effect-value compact">{escape(event_type)}</div>
                        </div>
                        <div class="event-effect-summary-item">
                            <div class="event-effect-label">发布状态</div>
                            <div class="event-effect-value compact">{escape(publish_status)}</div>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if not option_results:
                continue
            st.markdown(
                '<div class="event-branch-heading">投票分布</div>'
                f'<div class="event-branch-meta">总票数 {total_votes:,} · '
                f'当前领先：{escape(winner_label)}</div>',
                unsafe_allow_html=True,
            )
            for item in option_results:
                count = int(item["count"])
                ratio = count / total_votes if total_votes else 0
                percent = int(round(ratio * 100))
                st.progress(
                    ratio,
                    text=f"{item['marker']}. {item['option']} · {count} 票 · {percent}%",
                )


def _render_event_effect_archive(
    st,
    analytics_rows: list[dict],
    event_status_lookup: dict[int, dict] | None = None,
) -> None:
    archive = _group_event_effects_by_week_day(analytics_rows)
    day_count = sum(len(days) for days in archive.values())
    st.markdown(
        '<div class="event-archive-overview"><span>按周与日期逐级展开</span>'
        f'<strong>{_event_effect_count(analytics_rows)} 个活动 · '
        f'{len(archive)} 个周 · {day_count} 个日期</strong></div>',
        unsafe_allow_html=True,
    )
    with st.container(key="event_effect_archive_tree"):
        for week_index, (week_start, days) in enumerate(archive.items()):
            week_rows = [row for day_rows in days.values() for row in day_rows]
            iso_year, iso_week, _ = week_start.isocalendar()
            with st.expander(
                _event_week_archive_label(week_start, week_rows),
                expanded=week_index == 0,
                key=f"event_effect_week_{iso_year}_{iso_week}",
            ):
                for day_index, (archive_date, day_rows) in enumerate(days.items()):
                    with st.expander(
                        _event_day_archive_label(archive_date, day_rows),
                        expanded=week_index == 0 and day_index == 0,
                        key=f"event_effect_day_{archive_date:%Y_%m_%d}",
                        type="compact",
                    ):
                        _render_event_effect_cards(st, day_rows, event_status_lookup)


def _render_create_event_dialog(st, events: EventRepository, channels: list[dict]) -> None:
    @st.dialog("新建活动", width="large")
    def _dialog() -> None:
        st.caption("填写活动内容与发布计划，创建后由 Discord Bot 按排期发布。")
        title = st.text_input("活动标题", key="create_event_title")
        content = st.text_area(
            "活动内容",
            height=120,
            key="create_event_content",
        )
        st.session_state.setdefault("create_event_image_version", 0)
        uploaded_image = st.file_uploader(
            "活动配图（可选）",
            type=("jpg", "jpeg", "png", "webp"),
            accept_multiple_files=False,
            key=f"create_event_image_{st.session_state.create_event_image_version}",
            help="图片将显示在 Discord 活动正文下方。支持 JPG、PNG、WebP，最大 8 MB。",
            max_upload_size=8,
        )
        image_payload: bytes | None = None
        image_validation_error: str | None = None
        if uploaded_image is not None:
            candidate_payload = uploaded_image.getvalue()
            try:
                image_info = validate_event_image(candidate_payload)
            except EventImageValidationError as exc:
                image_validation_error = str(exc)
                st.error(image_validation_error)
            else:
                image_payload = candidate_payload

                def _remove_uploaded_image() -> None:
                    st.session_state.create_event_image_version += 1

                with st.container(key="event_image_preview"):
                    preview_column, detail_column = st.columns([1.1, 0.9])
                    preview_column.image(
                        image_payload,
                        caption="活动配图预览",
                        width="stretch",
                    )
                    detail_column.markdown("**已选择图片**")
                    detail_column.caption(str(uploaded_image.name))
                    detail_column.caption(
                        f"{image_info.width} × {image_info.height} px · "
                        f"{len(image_payload) / 1024:.1f} KB"
                    )
                    detail_column.button(
                        "移除配图",
                        key="remove_create_event_image",
                        on_click=_remove_uploaded_image,
                        width="stretch",
                    )
        event_type = st.selectbox(
            "活动类型",
            EVENT_TYPES,
            format_func=lambda value: EVENT_TYPE_LABELS[value],
            key="create_event_type",
        )
        with st.form("create_event_form"):
            raw_options = None
            if event_type in EVENT_TYPES_WITH_OPTIONS:
                raw_options = st.text_area(
                    "选项",
                    height=90,
                    placeholder="每行一个选项，也可以用英文逗号分隔。",
                )
            else:
                st.caption("公告将按正文直接发布，无需配置选项。")
            if channels:
                selected_channel = st.selectbox(
                    "发布频道",
                    channels,
                    format_func=_channel_label,
                )
                channel_id = str(selected_channel["channel_id"])
            else:
                st.warning("还没有同步到 Discord 频道名称，请先启动 Bot，或暂时手动填写频道 ID。")
                channel_id = st.text_input("Discord 频道 ID")
            publish_left, publish_right = st.columns(2)
            publish_date = publish_left.date_input("发布日期", value=datetime.now().date())
            publish_clock = publish_right.time_input("发布时间", value=time(hour=18, minute=0))
            repeat_rule = st.text_input("重复规则", value="none")
            status = st.selectbox(
                "状态",
                EVENT_STATUSES,
                index=1,
                format_func=lambda value: EVENT_STATUS_LABELS[value],
            )
            submitted = st.form_submit_button(
                "创建活动",
                type="primary",
                width="stretch",
                disabled=image_validation_error is not None,
            )
            if not submitted:
                return
            if not title or not content or not channel_id:
                st.error("活动标题、内容和发布频道不能为空。")
                return

            normalized_publish_time = format_datetime(
                datetime.combine(publish_date, publish_clock)
            )
            stored_image_path = None
            try:
                if image_payload is not None:
                    stored_image_path = save_event_image(events.db_path, image_payload)
                event_id = events.create(
                    title=title,
                    content=content,
                    event_type=event_type,
                    channel_id=channel_id,
                    publish_time=normalized_publish_time,
                    repeat_rule=repeat_rule,
                    status=status,
                    event_options_json=_event_options_json(event_type, raw_options),
                    event_image_path=stored_image_path,
                )
            except EventImageValidationError as exc:
                st.error(str(exc))
                return
            except Exception:
                delete_event_image(events.db_path, stored_image_path)
                raise
            _clear_event_caches(st)
            st.session_state.create_event_image_version += 1
            if status == "Scheduled":
                notice = (
                    f"活动 #{event_id} 已创建并排期。请确认 Discord Bot 正在运行；"
                    "到达发布时间后，Bot 会在约 30 秒内尝试发布到对应频道。"
                    "活动发布成功后才会计入活动效果；若超过 60 秒仍未发布，请检查频道权限。"
                )
            else:
                notice = f"活动 #{event_id} 已创建为草稿，不会自动发布到 Discord。"
            st.session_state["event_create_notice"] = notice
            st.rerun()

    _dialog()


def render(st, db_path) -> None:
    _render_event_management_css(st)
    events = EventRepository(db_path)
    channels = _cached_publishable_channels(st, db_path)
    channel_lookup = {str(channel["channel_id"]): _channel_label(channel) for channel in channels}

    notice = st.session_state.pop("event_create_notice", None)
    if notice:
        st.success(str(notice))
    refresh_notice = st.session_state.pop("event_refresh_notice", None)
    if refresh_notice:
        st.toast(str(refresh_notice), icon="🔄")
    if st.session_state.pop("_event_create_dialog_requested", False):
        _render_create_event_dialog(st, events, channels)

    st.markdown(
        """
        <div class="workbench-strip">
            <div>
                <div class="workbench-title">活动效果</div>
                <div class="workbench-subtitle">先查看参与与消息互动概览，再展开单个活动查看投票分布。</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    event_rows = _cached_event_rows(st, db_path, "All", "All")
    analytics_rows = _cached_analytics_rows(st, db_path, 100)
    event_status_lookup = {
        int(row["ID"]): row
        for row in _format_event_rows(event_rows, channel_lookup)
        if row.get("ID") is not None
    }
    analytics_filter_options = _analytics_filter_options(analytics_rows)
    with st.container(key="event_effect_console", border=True):
        effect_filter_columns = st.columns([2.4, 0.9, 1.1], vertical_alignment="bottom")
        selected_filter = effect_filter_columns[0].selectbox(
            "查看活动效果",
            analytics_filter_options,
            format_func=lambda option: option[0],
        )
        if effect_filter_columns[1].button(
            "刷新同步",
            key="refresh_event_effects",
            help="重新读取活动主表，以及 Discord Bot 最近写入的发布与互动状态。",
            width="stretch",
        ):
            _clear_event_caches(st)
            st.session_state["event_refresh_notice"] = "已同步最新活动与 Discord 互动状态。"
            st.rerun()
        filtered_analytics_rows = _filter_analytics_rows(
            analytics_rows,
            selected_filter[1],
        )
        effect_filter_columns[2].download_button(
            "导出效果 CSV",
            data=records_to_csv(filtered_analytics_rows),
            file_name="event_analytics.csv",
            mime="text/csv",
            width="stretch",
        )
        _render_event_overview(
            st,
            _event_analytics_overview(filtered_analytics_rows),
        )
        st.caption("活动数、参与人数与消息互动均来自 Discord 发布和同步结果。")
        _render_event_status_strip(st, event_rows)
    overdue_events = _overdue_scheduled_events(event_rows)
    if overdue_events:
        overdue_labels = "、".join(
            f"#{row.get('id')} · {row.get('title') or '未命名活动'} · "
            f"{channel_lookup.get(str(row.get('channel_id') or ''), row.get('channel_id') or '未知频道')}"
            for row in overdue_events[:3]
        )
        st.warning(
            f"{len(overdue_events)} 个活动已超过发布时间但尚未发布：{overdue_labels}。"
            "请检查 Bot 在目标频道的查看频道、发送消息与附加文件权限；权限补齐后 Bot 会自动重试。",
            icon="⚠️",
        )
    if filtered_analytics_rows:
        _render_event_effect_archive(st, filtered_analytics_rows, event_status_lookup)
    else:
        st.markdown('<div class="empty-state">暂无活动效果数据。活动发布并产生互动后会在这里显示。</div>', unsafe_allow_html=True)
