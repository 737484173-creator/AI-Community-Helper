from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from pathlib import Path

from app.dashboard.views.chat_monitor import (
    _close_calendar_dialog,
    _dedupe_nearby_duplicates,
    _risk_counts_for_records,
    _render_overview,
    _render_chat_monitor_css,
    _render_trend,
    _period_change_label,
    _risk_axis_max,
    _risk_date_tick_values,
    _risk_trend_daily_dataframe,
    _risk_selector_label,
    _replace_discord_mentions,
    _shift_month,
)
from app.database.migrations.init_db import init_database
from app.database.repositories.discord_channel_repository import DiscordChannelRepository
from app.database.repositories.message_repository import MessageRepository


class MarkdownCapture:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def markdown(self, body: str, **_kwargs) -> None:
        self.calls.append(body)


class TrendCapture(MarkdownCapture):
    def __init__(self) -> None:
        super().__init__()
        self.chart_spec: dict | None = None

    def container(self, **_kwargs):
        return nullcontext()

    def altair_chart(self, chart, **_kwargs) -> None:
        self.chart_spec = chart.to_dict()


def test_dedupe_nearby_duplicates_keeps_one_record_per_short_window() -> None:
    records = [
        {
            "id": 3,
            "discord_user_id": "discord-1",
            "channel_id": "channel-1",
            "message_source": "频道消息",
            "message": "Fixed mate!",
            "created_time": "2026-08-06 01:49:30",
        },
        {
            "id": 2,
            "discord_user_id": "discord-1",
            "channel_id": "channel-1",
            "message_source": "频道消息",
            "message": "Fixed mate!",
            "created_time": "2026-08-06 01:49:29",
        },
        {
            "id": 1,
            "discord_user_id": "discord-1",
            "channel_id": "channel-1",
            "message_source": "频道消息",
            "message": "Fixed mate!",
            "created_time": "2026-08-06 01:50:20",
        },
    ]

    deduped = _dedupe_nearby_duplicates(records)

    assert [record["id"] for record in deduped] == [3, 1]


def test_shift_month_handles_year_boundaries() -> None:
    assert _shift_month(date(2026, 1, 15), -1) == date(2025, 12, 1)
    assert _shift_month(date(2026, 12, 15), 1) == date(2027, 1, 1)


def test_close_calendar_dialog_clears_open_state() -> None:
    state = {"chat_calendar_open": True}

    _close_calendar_dialog(state)

    assert state["chat_calendar_open"] is False


def test_risk_counts_can_limit_calendar_to_pending_records() -> None:
    records = [
        {"created_time": "2026-08-06 08:40:00", "status": "待处理"},
        {"created_time": "2026-08-06 09:10:00", "status": "已处理"},
        {"created_time": "2026-08-07 10:00:00", "status": "待处理"},
    ]

    assert _risk_counts_for_records(records, status="待处理") == {
        "2026-08-06": 1,
        "2026-08-07": 1,
    }


def test_risk_trend_daily_dataframe_keeps_zero_days_and_flags_spikes() -> None:
    records = [
        {"created_time": "2026-08-01 09:00:00", "risk_level": "低风险"},
        {"created_time": "2026-08-02 09:00:00", "risk_level": "低风险"},
        {"created_time": "2026-08-03 09:00:00", "risk_level": "中风险"},
        *[
            {"created_time": "2026-08-04 09:00:00", "risk_level": "高风险"}
            for _ in range(4)
        ],
    ]

    daily = _risk_trend_daily_dataframe(records, date(2026, 8, 1), date(2026, 8, 5))

    assert daily["风险总量"].tolist() == [1, 1, 1, 4, 0]
    assert bool(daily.loc[3, "异常峰值"]) is True
    assert daily.loc[3, "高风险明细"] == "4 条 · 100%"
    assert daily.loc[4, "低风险明细"] == "0 条 · 0%"


def test_period_change_label_handles_zero_baselines_and_direction() -> None:
    assert _period_change_label(5, 0) == ("上期为 0", "up")
    assert _period_change_label(5, 10) == ("↓ 50%", "down")
    assert _period_change_label(10, 5) == ("↑ 100%", "up")


def test_risk_date_ticks_prioritize_days_with_risk() -> None:
    daily = _risk_trend_daily_dataframe(
        [
            {"created_time": "2026-08-02 09:00:00", "risk_level": "低风险"},
            {"created_time": "2026-08-05 09:00:00", "risk_level": "高风险"},
        ],
        date(2026, 8, 1),
        date(2026, 8, 7),
    )

    tick_dates = {value.date() for value in _risk_date_tick_values(daily, max_ticks=6)}

    assert date(2026, 8, 2) in tick_dates
    assert date(2026, 8, 5) in tick_dates


def test_risk_axis_max_adds_integer_headroom() -> None:
    assert _risk_axis_max(0) == 1
    assert _risk_axis_max(10) == 12


def test_risk_trend_chart_uses_one_canvas_with_line_above_bars() -> None:
    st = TrendCapture()
    records = [
        {"created_time": "2026-08-01 09:00:00", "risk_level": "低风险"},
        {"created_time": "2026-08-02 09:00:00", "risk_level": "高风险"},
    ]

    _render_trend(st, date(2026, 8, 1), date(2026, 8, 3), records, previous_total=1)

    assert st.chart_spec is not None
    assert "vconcat" not in st.chart_spec
    assert len(st.chart_spec["layer"]) == 11
    assert st.chart_spec["height"] == 340
    assert "周期风险" in st.calls[1]
    assert "总风险</span>" not in st.calls[0]


def test_risk_selector_label_keeps_context_without_a_duplicate_table() -> None:
    label = _risk_selector_label(
        {
            "id": 162,
            "created_time": "2026-08-06 08:40:00",
            "risk_level": "低风险",
            "channel_name": "game-chat",
            "message": "I will shut this bot right now",
        }
    )

    assert label == "#162 · 2026/08/06 08:40 · 低风险 · #game-chat · I will shut this bot right now"


def test_discord_mentions_render_as_names_without_exposing_ids() -> None:
    rendered = _replace_discord_mentions(
        "<@1340955757465698354> hello <@!999>",
        {"1340955757465698354": "Saris"},
    )

    assert rendered == "@Saris hello @未知用户"


def test_risk_overview_uses_one_prioritized_pulse_instead_of_metric_cards() -> None:
    st = MarkdownCapture()

    _render_overview(
        st,
        today_count=2,
        yesterday_count=1,
        week_count=8,
        high_pending_count=1,
        pending_count=4,
        merge_duplicates=True,
    )

    markup = st.calls[0]
    assert "chat-risk-pulse" in markup
    assert 'chat-risk-primary danger' in markup
    assert "近 30 日待处理" in markup and ">4</strong>" in markup
    assert "较昨日 +1" in markup
    assert "已合并疑似重复记录" in markup
    assert "chat-risk-card" not in markup


def test_risk_overview_has_a_clear_empty_queue_state() -> None:
    st = MarkdownCapture()

    _render_overview(st, 0, 0, 0, 0, 0, False)

    markup = st.calls[0]
    assert 'chat-risk-primary clear' in markup
    assert "当前风险队列已经清空" in markup
    assert "保留疑似重复记录" in markup


def test_risk_overview_styles_include_hover_feedback_and_reduced_motion() -> None:
    st = MarkdownCapture()

    _render_chat_monitor_css(st)

    styles = st.calls[0]
    assert ".chat-risk-pulse:hover" in styles
    assert ".chat-risk-scale-item:hover" in styles
    assert "prefers-reduced-motion: reduce" in styles


def test_message_repository_lists_multiple_prefixed_chat_channels(tmp_path: Path) -> None:
    db_path = tmp_path / "community.db"
    init_database(db_path)
    channels = DiscordChannelRepository(db_path)
    messages = MessageRepository(db_path)

    channel_names = {
        "game": "💬│game-chat",
        "help": "📌│ask_for_help",
        "discussion": "🥝│suggestion-discussion",
        "feedback": "🙋│feedback_wanted",
    }
    for channel_id, channel_name in channel_names.items():
        channels.upsert(channel_id, channel_name, "TextChannel", "guild-1")
        messages.create("player-1", channel_id, f"message in {channel_id}")

    rows = messages.list_channels_messages_between(
        start_time="2000-01-01 00:00:00",
        end_time="2099-01-01 00:00:00",
        channel_names=("game-chat", "ask_for_help", "suggestion-discussion"),
    )

    assert {row["channel_id"] for row in rows} == {"game", "help", "discussion"}
