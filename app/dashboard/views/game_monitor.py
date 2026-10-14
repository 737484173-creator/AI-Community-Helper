from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Iterable, Sequence

import altair as alt
import pandas as pd

from app.dashboard.design_tokens import COLORS
from app.dashboard.cache_utils import file_fingerprint
from app.dashboard.styles import icon_markdown, icon_svg
from app.dashboard.views.game_monitor_charts import risk_trend_chart as _risk_trend_chart
from app.dashboard.views.game_monitor_risk import (
    player_ranking_html,
    player_risk_ranking,
    risk_excel_bytes,
    risk_export_frame,
    server_risk_chart,
    server_risk_distribution,
)
from app.database.repositories.game_chat_repository import GameChatRepository
from app.database.repositories.vip_ae_repository import AEVIPSnapshotRepository
from app.game_monitor.ae_sync import AEGameChatSyncError, AEGameChatSyncService
from app.vip.server_merges import server_merge_config_revision
from app.vip.ae_sync import DEFAULT_AE_PROJECT_ID
from app.vip.service import load_ae_vip_workbook


VIEW_OPTIONS = ("消息趋势", "风险言论")
TIME_RANGE_OPTIONS = ("今日", "近7日", "近30日", "自定义")
RISK_LEVEL_OPTIONS = ("全部", "高风险", "中风险", "低风险")
RISK_TYPE_OPTIONS = ("全部", "脏字/攻击", "强烈负面", "高强度情绪", "风险表达")
SORT_OPTIONS = ("最新时间", "高风险优先")
RISK_ORDER = {"高风险": 0, "中风险": 1, "低风险": 2}


def render(st, db_path: str | Path) -> None:
    _inject_styles(st)
    repository = GameChatRepository(db_path)
    today = date.today()
    active_role_count = _active_role_count(db_path)
    active_role_label = (
        f"{active_role_count} 个有效角色" if active_role_count else "当前有效角色"
    )

    st.session_state.setdefault("game_monitor_view", "消息趋势")
    st.session_state.setdefault("game_monitor_range", "近30日")
    with st.container(key="game_monitor_view_bar", border=False):
        view_col, context_col = st.columns([1.55, 4.45], vertical_alignment="center")
        with view_col:
            view = st.segmented_control(
                "游戏内监控视图",
                options=VIEW_OPTIONS,
                key="game_monitor_view",
                label_visibility="collapsed",
            ) or "消息趋势"
        with context_col:
            st.markdown(
                f"""
                <div class="game-monitor-context">
                    <span class="game-monitor-context-icon">{icon_svg('radar')}</span>
                    <span><strong>游戏内聊天</strong> · AE role_chat</span>
                    <span class="game-monitor-context-detail">{active_role_label} · chat_content · 仅监控</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with st.container(key="game_monitor_command_panel", border=True):
        range_name, custom_start, custom_end = _render_time_controls(st, today)
        start_date, end_date = resolve_date_range(
            range_name,
            today,
            custom_start=custom_start,
            custom_end=custom_end,
        )
        if start_date > end_date:
            st.error("开始日期不能晚于结束日期。")
            return

        server_rows = repository.list_servers(
            DEFAULT_AE_PROJECT_ID,
            start_date.isoformat(),
            end_date.isoformat(),
        )
        server_labels = {
            str(row["server_id"]): _server_label(row["server_id"], row["server_name"])
            for row in server_rows
        }

        filter_col, sync_col = st.columns([4.9, 1.1], vertical_alignment="bottom")
        with filter_col:
            selected_servers = st.multiselect(
                "区服（可多选对比）",
                options=tuple(server_labels),
                format_func=lambda value: server_labels.get(value, value),
                placeholder="全部区服（默认总览）",
                key="game_monitor_servers",
            )
        with sync_col:
            sync_requested = st.button(
                f"{icon_markdown('refresh', COLORS['primary'])} 同步 AE 数据",
                key="game_monitor_sync",
                use_container_width=True,
                help=f"同步当前时间范围内{active_role_label}的游戏内发言。",
            )

    if sync_requested:
        _run_sync(st, db_path, start_date, end_date)

    try:
        rows = _load_rows(
            st,
            db_path,
            start_date,
            end_date,
            selected_servers,
        )
        latest_run = repository.get_latest_run(DEFAULT_AE_PROJECT_ID)
        covering_run = repository.get_covering_success(
            DEFAULT_AE_PROJECT_ID,
            start_date.isoformat(),
            end_date.isoformat(),
        )
    except Exception as exc:
        st.error(f"游戏内消息加载失败：{exc}")
        return

    _render_data_status(st, latest_run, covering_run, start_date, end_date)
    if view == "风险言论":
        _render_risk_view(
            st,
            rows,
            db_path=db_path,
            start_date=start_date,
            end_date=end_date,
            covering_run=covering_run,
        )
    else:
        _render_trend_view(
            st,
            rows,
            start_date=start_date,
            end_date=end_date,
            selected_servers=selected_servers,
            covering_run=covering_run,
        )


def resolve_date_range(
    range_name: str,
    today: date,
    *,
    custom_start: date | None = None,
    custom_end: date | None = None,
) -> tuple[date, date]:
    if range_name == "今日":
        return today, today
    if range_name == "近7日":
        return today - timedelta(days=6), today
    if range_name == "自定义":
        return custom_start or today - timedelta(days=29), custom_end or today
    return today - timedelta(days=29), today


def to_dataframe(rows: Iterable[object]) -> pd.DataFrame:
    records = [dict(row) for row in rows]
    columns = (
        "message_key",
        "event_time",
        "role_id",
        "server_id",
        "server_name",
        "chat_content",
        "chat_channel",
        "chat_type",
        "risk_level",
        "risk_type",
        "risk_reason",
    )
    dataframe = pd.DataFrame(records)
    for column in columns:
        if column not in dataframe.columns:
            dataframe[column] = None
    dataframe["event_time"] = pd.to_datetime(dataframe["event_time"], errors="coerce")
    return dataframe.dropna(subset=["event_time"])


def daily_message_trend(
    dataframe: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    calendar_days = pd.date_range(start_date, end_date, freq="D")
    if dataframe.empty:
        counts = pd.Series(0, index=calendar_days, dtype="int64")
    else:
        counts = (
            dataframe.assign(date=dataframe["event_time"].dt.normalize())
            .groupby("date")
            .size()
            .reindex(calendar_days, fill_value=0)
        )
    output = pd.DataFrame({"日期": calendar_days, "消息数": counts.astype(int).values})
    baseline = output["消息数"].shift(1).rolling(7, min_periods=3)
    output["基线"] = baseline.mean()
    output["波动"] = baseline.std().fillna(0)
    gap = output["消息数"] - output["基线"]
    output["异常峰值"] = (
        output["基线"].notna()
        & (output["消息数"] >= output["基线"] * 1.6)
        & (gap >= output["波动"] * 2)
        & (gap >= 3)
    )
    return output


def period_change(dataframe: pd.DataFrame) -> tuple[float | None, str]:
    if len(dataframe) < 2:
        return None, "暂无环比"
    split = max(len(dataframe) // 2, 1)
    previous = int(dataframe.iloc[:split]["消息数"].sum())
    current = int(dataframe.iloc[split:]["消息数"].sum())
    if previous == 0:
        return (None, "较前期新增") if current else (0.0, "与前期持平")
    delta = (current - previous) / previous
    direction = "上升" if delta > 0 else "下降" if delta < 0 else "持平"
    return delta, f"较前期{direction} {abs(delta):.1%}"


def sort_risk_messages(dataframe: pd.DataFrame, sort_name: str) -> pd.DataFrame:
    output = dataframe.copy()
    if output.empty:
        return output
    if sort_name == "高风险优先":
        output["_risk_order"] = output["risk_level"].map(RISK_ORDER).fillna(99)
        output = output.sort_values(
            ["_risk_order", "event_time"],
            ascending=[True, False],
        ).drop(columns=["_risk_order"])
        return output
    return output.sort_values("event_time", ascending=False)


def daily_risk_trend(
    dataframe: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Build the shared daily risk shape used by the game-monitor trend chart."""
    calendar_days = pd.date_range(start_date, end_date, freq="D")
    levels = tuple(RISK_ORDER)
    risk_rows = dataframe[dataframe["risk_level"].isin(levels)].copy()
    if risk_rows.empty:
        daily = pd.DataFrame(index=calendar_days, columns=levels).fillna(0)
    else:
        grouped = (
            risk_rows.assign(日期=risk_rows["event_time"].dt.normalize())
            .groupby(["日期", "risk_level"])
            .size()
            .unstack(fill_value=0)
            .reindex(calendar_days, fill_value=0)
        )
        daily = grouped.reindex(columns=levels, fill_value=0)

    daily = daily.reset_index(names="日期")
    for level in levels:
        daily[level] = daily[level].fillna(0).astype(int)
    daily["风险总量"] = daily[list(levels)].sum(axis=1).astype(int)
    daily["完整日期"] = daily["日期"].dt.strftime("%Y-%m-%d")
    for level in levels:
        percentages = [
            (int(count) / int(total) * 100) if int(total) else 0
            for count, total in zip(daily[level], daily["风险总量"], strict=True)
        ]
        daily[f"{level}明细"] = [
            f"{int(count)} 条 · {percentage:.0f}%"
            for count, percentage in zip(daily[level], percentages, strict=True)
        ]
    return daily


def _render_time_controls(st, today: date) -> tuple[str, date | None, date | None]:
    range_name = st.segmented_control(
        "时间范围",
        options=TIME_RANGE_OPTIONS,
        key="game_monitor_range",
    ) or "近30日"
    if range_name != "自定义":
        return range_name, None, None

    st.session_state.setdefault("game_monitor_custom_start", today - timedelta(days=29))
    st.session_state.setdefault("game_monitor_custom_end", today)
    start_col, end_col = st.columns(2)
    custom_start = start_col.date_input(
        "开始日期",
        max_value=today,
        key="game_monitor_custom_start",
    )
    custom_end = end_col.date_input(
        "结束日期",
        max_value=today,
        key="game_monitor_custom_end",
    )
    return range_name, custom_start, custom_end


def _run_sync(st, db_path: str | Path, start_date: date, end_date: date) -> None:
    try:
        with st.spinner("正在从 AE 同步当前有效角色的游戏内发言…"):
            result = AEGameChatSyncService(db_path).sync(start_date, end_date)
    except AEGameChatSyncError as exc:
        st.error(f"游戏内消息同步失败：{exc}")
        return
    st.toast(
        f"同步完成：{result.matched_row_count} 条发言，"
        f"其中 {result.risk_row_count} 条命中风险规则。"
    )
    st.rerun()


def _active_role_count(db_path: str | Path) -> int:
    try:
        workbook = load_ae_vip_workbook(db_path, DEFAULT_AE_PROJECT_ID)
    except Exception:
        return 0
    return int(len(workbook.active_df)) if workbook is not None else 0


def _load_rows(
    st,
    db_path: str | Path,
    start_date: date,
    end_date: date,
    server_ids: Sequence[str],
):
    @st.cache_data(ttl=15, show_spinner=False)
    def _cached(
        path: str,
        start: str,
        end: str,
        servers: tuple[str, ...],
        database_fingerprint: tuple[int, int],
        merge_revision: tuple[int, int],
    ):
        del database_fingerprint, merge_revision
        return [
            dict(row)
            for row in GameChatRepository(path).list_messages(
                DEFAULT_AE_PROJECT_ID,
                start,
                end,
                server_ids=servers,
            )
        ]

    return _cached(
        str(db_path),
        start_date.isoformat(),
        end_date.isoformat(),
        tuple(str(value) for value in server_ids),
        file_fingerprint(Path(db_path)),
        server_merge_config_revision(),
    )


def _render_data_status(st, latest_run, covering_run, start_date: date, end_date: date) -> None:
    if latest_run and latest_run["status"] == "FAILED":
        error_message = escape(str(latest_run["error_message"] or "未知错误"))
        st.markdown(
            f"""
            <div class="game-monitor-signal danger">
                {icon_svg('alert')}
                <span><strong>最近一次 AE 同步失败</strong>，当前继续展示已缓存数据。
                原因：{error_message}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    if covering_run:
        synced_at = _format_sync_time(covering_run["finished_at"])
        st.markdown(
            f"""
            <div class="game-monitor-data-status">
                <span class="game-monitor-data-dot"></span>
                <span>数据范围 <strong>{start_date:%Y/%m/%d}–{end_date:%Y/%m/%d}</strong></span>
                <span>有效角色 <strong>{covering_run['active_role_count']}</strong></span>
                <span>最近同步 <strong>{escape(synced_at)}</strong></span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f"""
        <div class="game-monitor-signal warning">
            {icon_svg('database')}
            <span><strong>当前时间范围尚未完成同步</strong>，页面展示已有缓存数据；
            点击“同步 AE 数据”可补齐 {start_date:%Y/%m/%d}–{end_date:%Y/%m/%d}。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_trend_view(
    st,
    rows,
    *,
    start_date: date,
    end_date: date,
    selected_servers: Sequence[str],
    covering_run,
) -> None:
    dataframe = to_dataframe(rows)
    daily = daily_message_trend(dataframe, start_date, end_date)
    total_messages = int(len(dataframe))
    active_roles = int(dataframe["role_id"].nunique()) if total_messages else 0
    average_per_role = total_messages / active_roles if active_roles else 0.0
    risk_messages = int(dataframe["risk_level"].notna().sum()) if total_messages else 0
    change, change_label = period_change(daily)

    _render_metric_strip(
        st,
        (
            ("消息总量", f"{total_messages:,}", change_label, _change_tone(change)),
            ("发言角色", f"{active_roles:,}", "去重角色 ID", "neutral"),
            ("角色人均", f"{average_per_role:.1f}", "条 / 角色", "neutral"),
            ("风险消息", f"{risk_messages:,}", "沿用聊天监控规则", "danger" if risk_messages else "neutral"),
        ),
    )

    if dataframe.empty:
        _render_empty_state(
            st,
            covering_run,
            "选定范围内，当前有效角色没有匹配到游戏内发言。",
        )
        return

    anomalies = daily[daily["异常峰值"]]
    if not anomalies.empty:
        peak = anomalies.sort_values("消息数", ascending=False).iloc[0]
        st.markdown(
            f"""
            <div class="game-monitor-signal warning">
                {icon_svg('alert')}
                <span>检测到 <strong>{len(anomalies)} 个异常峰值</strong>；最高出现在
                {peak['日期']:%Y/%m/%d}，共 {int(peak['消息数']):,} 条游戏内消息。</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    chart_col, ranking_col = st.columns([1.75, 1], gap="large")
    with chart_col:
        with st.container(key="game_monitor_trend_workspace", border=True):
            _render_panel_heading(
                st,
                "游戏内消息趋势",
                "按天统计发言数量；菱形标记表示相对前 7 日基线的异常峰值。",
                "analytics",
            )
            chart = _trend_chart(dataframe, daily, start_date, end_date, selected_servers)
            st.altair_chart(chart, use_container_width=True)

    with ranking_col:
        with st.container(key="game_monitor_ranking_workspace", border=True):
            _render_panel_heading(
                st,
                "区服消息量排行",
                "按当前时间与区服筛选口径统计。",
                "bar",
            )
            ranking = (
                dataframe.assign(
                    区服=dataframe.apply(
                        lambda row: _server_label(row["server_id"], row["server_name"]), axis=1
                    )
                )
                .groupby("区服", as_index=False)
                .size()
                .rename(columns={"size": "消息数"})
                .sort_values("消息数", ascending=False)
                .head(12)
            )
            ranking_chart = _ranking_chart(ranking)
            st.altair_chart(_style_chart(ranking_chart), use_container_width=True)


def _trend_chart(
    dataframe: pd.DataFrame,
    daily: pd.DataFrame,
    start_date: date,
    end_date: date,
    selected_servers: Sequence[str],
) -> alt.Chart:
    x = alt.X("日期:T", title=None, axis=alt.Axis(format="%-m/%-d", labelAngle=0))
    y = alt.Y("消息数:Q", title="消息数", axis=alt.Axis(tickMinStep=1))
    if len(selected_servers) > 1:
        days = pd.date_range(start_date, end_date, freq="D")
        server_frame = dataframe.assign(
            日期=dataframe["event_time"].dt.normalize(),
            区服=dataframe.apply(
                lambda row: _server_label(row["server_id"], row["server_name"]), axis=1
            ),
        )
        grouped = server_frame.groupby(["日期", "区服"]).size().rename("消息数")
        labels = sorted(server_frame["区服"].dropna().unique())
        complete_index = pd.MultiIndex.from_product([days, labels], names=["日期", "区服"])
        comparison = grouped.reindex(complete_index, fill_value=0).reset_index()
        hover = alt.selection_point(
            name="game_message_compare_hover",
            fields=["日期", "区服"],
            nearest=True,
            on="pointerover",
            clear="pointerout",
            empty=False,
        )
        color = alt.Color(
            "区服:N",
            title="区服",
            scale=alt.Scale(
                range=[
                    COLORS["primary"],
                    COLORS["accent"],
                    COLORS["success"],
                    COLORS["warning"],
                    COLORS["danger"],
                    COLORS["risk_low"],
                ]
            ),
        )
        base = alt.Chart(comparison).encode(x=x, y=y, color=color)
        line = base.mark_line(strokeWidth=2.4)
        points = base.mark_point(filled=True, stroke=COLORS["card"], strokeWidth=1.5).encode(
            size=alt.condition(hover, alt.value(112), alt.value(34), empty=False),
            opacity=alt.condition(hover, alt.value(1), alt.value(0.68), empty=False),
        )
        guide = alt.Chart(comparison).mark_rule(
            color=COLORS["primary"], strokeDash=[3, 4], strokeWidth=1
        ).encode(
            x=x,
            opacity=alt.condition(hover, alt.value(0.34), alt.value(0), empty=False),
        )
        selector = base.mark_point(opacity=0).encode(
            tooltip=[
                alt.Tooltip("日期:T", format="%Y/%m/%d"),
                "区服:N",
                alt.Tooltip("消息数:Q", format=",d"),
            ]
        ).add_params(hover)
        comparison_chart = (
            alt.layer(line, points, guide, selector)
            .properties(height=350)
            .interactive(bind_y=False)
        )
        return _style_chart(comparison_chart)

    hover = alt.selection_point(
        name="game_message_date_hover",
        fields=["日期"],
        nearest=True,
        on="pointerover",
        clear="pointerout",
        empty=False,
    )
    base = alt.Chart(daily).encode(x=x, y=y)
    area = base.mark_area(color=COLORS["primary"], opacity=0.08, interpolate="monotone")
    line = base.mark_line(color=COLORS["primary"], strokeWidth=2.6, interpolate="monotone")
    points = base.mark_point(
        filled=True,
        stroke=COLORS["primary"],
        strokeWidth=1.8,
    ).encode(
        size=alt.condition(hover, alt.value(118), alt.value(34), empty=False),
        fill=alt.condition(
            hover,
            alt.value(COLORS["primary"]),
            alt.value(COLORS["card"]),
            empty=False,
        ),
    )
    guide = alt.Chart(daily).mark_rule(
        color=COLORS["primary"], strokeDash=[3, 4], strokeWidth=1
    ).encode(
        x=x,
        opacity=alt.condition(hover, alt.value(0.32), alt.value(0), empty=False),
    )
    selector = base.mark_point(opacity=0).encode(
        tooltip=[
            alt.Tooltip("日期:T", format="%Y/%m/%d"),
            alt.Tooltip("消息数:Q", format=",d"),
        ]
    ).add_params(hover)
    chart = area + line + points + guide + selector
    peak_rows = daily[daily["异常峰值"]]
    if not peak_rows.empty:
        peaks = (
            alt.Chart(peak_rows)
            .mark_point(shape="diamond", size=150, color=COLORS["danger"], filled=True)
            .encode(
                x=x,
                y=y,
                tooltip=[
                    alt.Tooltip("日期:T", format="%Y/%m/%d"),
                    alt.Tooltip("消息数:Q", format=",d"),
                    alt.Tooltip("基线:Q", format=".1f"),
                ],
            )
        )
        chart = chart + peaks
    return _style_chart(chart.properties(height=350))


def _ranking_chart(ranking: pd.DataFrame) -> alt.Chart:
    hover = alt.selection_point(
        name="game_server_bar_hover",
        fields=["区服"],
        on="pointerover",
        clear="pointerout",
        empty=False,
    )
    return (
        alt.Chart(ranking)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X("消息数:Q", title=None, axis=alt.Axis(grid=False)),
            y=alt.Y("区服:N", sort="-x", title=None),
            color=alt.condition(
                hover,
                alt.value(COLORS["primary_hover"]),
                alt.value(COLORS["primary"]),
                empty=False,
            ),
            opacity=alt.condition(hover, alt.value(1), alt.value(0.82), empty=False),
            stroke=alt.condition(
                hover,
                alt.value(COLORS["primary_hover"]),
                alt.value(COLORS["primary"]),
                empty=False,
            ),
            strokeWidth=alt.condition(hover, alt.value(1.5), alt.value(0), empty=False),
            tooltip=["区服:N", alt.Tooltip("消息数:Q", format=",d")],
        )
        .add_params(hover)
        .properties(height=max(280, min(len(ranking), 12) * 27))
    )


def _render_risk_view(
    st,
    rows,
    *,
    db_path: str | Path,
    start_date: date,
    end_date: date,
    covering_run,
) -> None:
    dataframe = to_dataframe(rows)
    all_message_count = len(dataframe)
    risk = dataframe[dataframe["risk_level"].notna()].copy()

    with st.container(key="game_monitor_risk_filter_panel", border=True):
        level_col, type_col, sort_col = st.columns([1, 1.25, 1])
        risk_level = level_col.selectbox(
            "风险等级",
            options=RISK_LEVEL_OPTIONS,
            key="game_monitor_risk_level",
        )
        risk_type = type_col.selectbox(
            "风险类型",
            options=RISK_TYPE_OPTIONS,
            key="game_monitor_risk_type",
        )
        sort_name = sort_col.selectbox(
            "排序方式",
            options=SORT_OPTIONS,
            key="game_monitor_risk_sort",
        )
    if risk_level != "全部":
        risk = risk[risk["risk_level"] == risk_level]
    if risk_type != "全部":
        risk = risk[risk["risk_type"] == risk_type]
    risk = sort_risk_messages(risk, sort_name)

    high_risk_count = int((risk["risk_level"] == "高风险").sum()) if not risk.empty else 0
    _render_metric_strip(
        st,
        (
            ("风险消息", f"{len(risk):,}", "当前筛选结果", "danger" if len(risk) else "neutral"),
            ("涉及角色", f"{risk['role_id'].nunique() if not risk.empty else 0:,}", "去重角色 ID", "neutral"),
            ("高风险消息", f"{high_risk_count:,}", "优先巡检", "danger" if high_risk_count else "neutral"),
        ),
    )

    if all_message_count == 0:
        _render_empty_state(
            st,
            covering_run,
            "选定范围内，当前有效角色没有匹配到游戏内发言。",
        )
        return
    if risk.empty:
        _render_state(
            st,
            tone="clear",
            title="当前筛选未命中风险言论",
            message="可调整风险等级、类型、区服或时间范围继续巡检。",
            icon_name="shield_check",
        )
        return

    try:
        profile_rows = AEVIPSnapshotRepository(db_path).list_snapshot(DEFAULT_AE_PROJECT_ID)
    except Exception:
        profile_rows = []

    with st.container(key="game_monitor_risk_trend_workspace", border=True):
        st.markdown(
            f"""
            <div class="game-risk-trend-header">
                <div class="game-panel-heading">
                    <span class="game-panel-icon">{icon_svg('analytics')}</span>
                    <div>
                        <div class="game-panel-title">游戏内风险趋势</div>
                        <div class="game-panel-caption">上层看每日风险总量，下层看高、中、低风险构成。</div>
                    </div>
                </div>
                <div class="game-risk-trend-legend" aria-label="风险等级图例">
                    <span><i class="danger"></i>高风险</span>
                    <span><i class="warning"></i>中风险</span>
                    <span><i class="muted"></i>低风险</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        risk_daily = daily_risk_trend(risk, start_date, end_date)
        st.altair_chart(
            _style_chart(_risk_trend_chart(risk_daily, start_date, end_date)),
            use_container_width=True,
        )

    analysis_columns = st.columns([1, 1.28], gap="large")
    with analysis_columns[0]:
        with st.container(key="game_monitor_risk_servers", border=True):
            _render_panel_heading(
                st,
                "风险区服分布",
                "按当前筛选结果汇总，高、中、低风险堆叠展示。",
                "bar",
            )
            distribution = server_risk_distribution(risk)
            st.altair_chart(
                _style_chart(server_risk_chart(distribution)),
                use_container_width=True,
            )

    ranking_type = "脏字/攻击" if risk_type == "全部" else risk_type
    ranking_source = risk[risk["risk_type"].eq(ranking_type)].copy()
    ranking_title = (
        "脏话数量最多的玩家"
        if ranking_type == "脏字/攻击"
        else f"{ranking_type}高频玩家"
    )
    with analysis_columns[1]:
        with st.container(key="game_monitor_risk_players", border=False):
            ranking = player_risk_ranking(ranking_source, profile_rows)
            st.markdown(
                player_ranking_html(ranking, ranking_source, ranking_title),
                unsafe_allow_html=True,
            )

    export = risk_export_frame(risk, profile_rows)
    with st.container(key="game_monitor_risk_export", border=True):
        export_copy, export_action = st.columns([4.6, 1.4], vertical_alignment="center")
        export_copy.markdown(
            f"**完整风险明细**  已收起；当前筛选共 {len(export):,} 条，可在此下载查看原文与命中规则。"
        )
        export_action.download_button(
            f"{icon_markdown('download', COLORS['primary'])} 下载 Excel",
            data=risk_excel_bytes(export),
            file_name=f"游戏内风险言论_{start_date:%Y%m%d}_{end_date:%Y%m%d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="game_monitor_risk_download",
        )


def _render_metric_strip(st, metrics: Sequence[tuple[str, str, str, str]]) -> None:
    items: list[str] = []
    for label, value, note, tone in metrics:
        safe_tone = tone if tone in {"neutral", "success", "danger"} else "neutral"
        items.append(
            f'<div class="game-kpi-item {safe_tone}">'
            f'<div class="game-kpi-label">{escape(label)}</div>'
            f'<div class="game-kpi-value">{escape(value)}</div>'
            f'<div class="game-kpi-note">{escape(note)}</div>'
            "</div>"
        )
    st.markdown(
        f'<section class="game-kpi-strip game-kpi-count-{len(items)}">'
        + "".join(items)
        + "</section>",
        unsafe_allow_html=True,
    )


def _render_panel_heading(st, title: str, caption: str, icon_name: str) -> None:
    st.markdown(
        f"""
        <div class="game-panel-heading">
            <span class="game-panel-icon">{icon_svg(icon_name)}</span>
            <div>
                <div class="game-panel-title">{escape(title)}</div>
                <div class="game-panel-caption">{escape(caption)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _change_tone(change: float | None) -> str:
    if change is None or change == 0:
        return "neutral"
    return "success" if change > 0 else "danger"


def _style_chart(chart):
    return (
        chart.configure_view(strokeOpacity=0)
        .configure_axis(
            labelColor=COLORS["text_secondary"],
            titleColor=COLORS["text_secondary"],
            domainColor=COLORS["border"],
            tickColor=COLORS["border"],
            gridColor=COLORS["surface_muted"],
            labelFont="Segoe UI",
            titleFont="Segoe UI",
        )
        .configure_legend(
            labelColor=COLORS["text_secondary"],
            titleColor=COLORS["text"],
            labelFont="Segoe UI",
            titleFont="Segoe UI",
        )
    )


def _render_empty_state(st, covering_run, message: str) -> None:
    if covering_run:
        _render_state(
            st,
            tone="clear",
            title="没有匹配到游戏内消息",
            message=message,
            icon_name="message",
        )
        return
    _render_state(
        st,
        tone="pending",
        title="当前时间范围尚未同步",
        message="点击“同步 AE 数据”后查看；这与“已同步但没有匹配消息”是不同状态。",
        icon_name="database",
    )


def _render_state(st, *, tone: str, title: str, message: str, icon_name: str) -> None:
    safe_tone = tone if tone in {"clear", "pending"} else "pending"
    st.markdown(
        f"""
        <section class="game-monitor-empty {safe_tone}" aria-label="{escape(title)}">
            <span class="game-monitor-empty-icon">{icon_svg(icon_name)}</span>
            <div>
                <div class="game-monitor-empty-title">{escape(title)}</div>
                <div class="game-monitor-empty-copy">{escape(message)}</div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _server_label(server_id: object, server_name: object) -> str:
    identifier = str(server_id or "").strip()
    name = str(server_name or "").strip()
    if name and identifier and name.casefold() not in {identifier.casefold(), f"s{identifier}".casefold()}:
        return f"{name}（{identifier}）"
    return name or (f"S{identifier}" if identifier else "未知区服")


def _format_sync_time(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "未知"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return text


def _inject_styles(st) -> None:
    style_path = Path(__file__).with_name("game_monitor.css")
    st.markdown(
        f"<style>{style_path.read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True,
    )
