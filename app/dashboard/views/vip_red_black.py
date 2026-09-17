from __future__ import annotations

from html import escape

import altair as alt
import pandas as pd

from app.dashboard.design_tokens import COLORS
from app.dashboard.views.vip_common import (
    amount_label,
    compact_multiselect_filter,
    render_player_table,
    section,
)
from app.dashboard.views.vip_operations import _current_source, load_current_workbook
from app.vip.analytics.red_black_list import (
    RED_BLACK_RULES,
    build_red_black_board,
    filter_board_candidates,
)
from app.vip.server_merges import server_merge_summary


def _render_chart_motion_css(st) -> None:
    st.markdown(
        """
        <style>
        .red-black-metric-band {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0;
            margin: 2px 0 22px;
            overflow: hidden;
            border-top: 1px solid var(--border-strong);
            border-bottom: 1px solid var(--border);
            background: color-mix(in srgb, var(--surface) 56%, transparent);
            animation: content-enter var(--motion-enter) var(--ease-standard) both;
            transform: translateY(0);
            transition:
                transform var(--motion-standard) var(--ease-standard),
                border-color var(--motion-standard) var(--ease-standard),
                background-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        .red-black-metric-band:hover {
            z-index: 1;
            transform: translateY(-2px);
            border-color: color-mix(in srgb, var(--primary) 22%, var(--border));
            background: color-mix(in srgb, var(--primary-soft) 16%, var(--surface));
            box-shadow: var(--shadow-2);
        }
        .red-black-metric-item {
            position: relative;
            min-width: 0;
            min-height: 118px;
            padding: 18px 18px 16px;
            overflow: hidden;
            background: transparent;
            transition:
                background-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        .red-black-metric-item + .red-black-metric-item {
            border-left: 1px solid var(--border);
        }
        .red-black-metric-item::after {
            position: absolute;
            right: 18px;
            bottom: 0;
            left: 18px;
            height: 2px;
            border-radius: 2px 2px 0 0;
            background: var(--primary);
            content: "";
            opacity: 0;
            transform: scaleX(.22);
            transform-origin: center;
            transition:
                opacity var(--motion-fast) var(--ease-standard),
                transform var(--motion-standard) var(--ease-standard);
        }
        .red-black-metric-item:hover {
            background: color-mix(in srgb, var(--primary-soft) 44%, transparent);
            box-shadow: inset 0 -1px 0 color-mix(in srgb, var(--primary) 14%, transparent);
        }
        .red-black-metric-item:hover::after {
            opacity: .78;
            transform: scaleX(1);
        }
        .red-black-metric-label {
            color: var(--text-secondary);
            font-size: 12px;
            font-weight: 650;
            line-height: 18px;
            text-wrap: pretty;
            transition: color var(--motion-standard) var(--ease-standard);
        }
        .red-black-metric-value {
            display: inline-block;
            margin: 7px 0 7px;
            color: var(--text-primary);
            font-size: clamp(31px, 3vw, 39px);
            font-weight: 730;
            font-variant-numeric: tabular-nums;
            line-height: 1;
            letter-spacing: -.045em;
            transform-origin: left center;
            transition:
                transform var(--motion-standard) var(--ease-standard),
                color var(--motion-standard) var(--ease-standard);
        }
        .red-black-metric-note {
            max-width: 25ch;
            color: var(--text-tertiary);
            font-size: 12px;
            line-height: 17px;
            text-wrap: pretty;
        }
        .red-black-metric-item:hover .red-black-metric-label {
            color: var(--primary-hover);
        }
        .red-black-metric-item:hover .red-black-metric-value {
            color: var(--primary-hover);
            transform: translateY(-1px) scale(1.025);
        }
        .red-black-metric-item.tone-red .red-black-metric-value { color: var(--danger); }
        .red-black-metric-item.tone-red:hover {
            background: color-mix(in srgb, var(--danger-soft) 66%, transparent);
        }
        .red-black-metric-item.tone-red::after { background: var(--danger); }
        .red-black-metric-item.tone-red:hover .red-black-metric-label,
        .red-black-metric-item.tone-red:hover .red-black-metric-value { color: var(--danger); }
        .red-black-metric-item.tone-black .red-black-metric-value { color: var(--accent); }
        .red-black-metric-item.tone-black::after { background: var(--accent); }
        .red-black-metric-item.tone-black:hover .red-black-metric-label,
        .red-black-metric-item.tone-black:hover .red-black-metric-value { color: var(--accent); }

        .st-key-vip_red_black_tabs [role="tab"] {
            outline: none !important;
            border-radius: 6px 6px 0 0;
            background-color: transparent !important;
            box-shadow: none !important;
            transition:
                color var(--motion-fast) var(--ease-standard),
                background-color var(--motion-fast) var(--ease-standard),
                box-shadow var(--motion-fast) var(--ease-standard);
        }
        .st-key-vip_red_black_tabs [role="tab"]:hover {
            background-color: color-mix(in srgb, var(--primary-soft) 30%, transparent) !important;
        }
        .st-key-vip_red_black_tabs [role="tab"]:focus:not(:focus-visible) {
            outline: none !important;
            background-color: transparent !important;
            box-shadow: none !important;
        }
        .st-key-vip_red_black_tabs [role="tab"]:focus-visible {
            outline: none !important;
            background-color: color-mix(in srgb, var(--primary-soft) 38%, transparent) !important;
            box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--primary) 34%, transparent) !important;
        }

        @keyframes red-black-chart-enter {
            from {
                opacity: 0;
                transform: translateY(8px);
                filter: saturate(.88);
            }
            to {
                opacity: 1;
                transform: translateY(0);
                filter: saturate(1);
            }
        }
        @keyframes red-black-bar-grow {
            from { transform: scaleX(.025); }
            to { transform: scaleX(1); }
        }
        [class*="st-key-red_black_rank_chart_"] .stVegaLiteChart {
            transition: filter var(--motion-standard) var(--ease-standard);
        }
        [class*="st-key-red_black_rank_chart_"] svg g.layer_1_marks path,
        [class*="st-key-red_black_rank_chart_"] svg g.layer_1_marks rect {
            transform-box: fill-box;
            transform-origin: left center;
            will-change: transform;
            animation: red-black-bar-grow 360ms cubic-bezier(.22, 1, .36, 1) both;
            transition: filter var(--motion-standard) var(--ease-standard);
        }
        [class*="st-key-red_black_rank_chart_"] svg g.layer_1_marks :is(path, rect):hover {
            filter: brightness(1.06) drop-shadow(0 2px 3px rgba(37, 99, 235, .18));
        }
        [class*="st-key-red_black_rank_chart_"] svg g.layer_1_marks :is(path, rect):nth-child(2) { animation-delay: 12ms; }
        [class*="st-key-red_black_rank_chart_"] svg g.layer_1_marks :is(path, rect):nth-child(3) { animation-delay: 24ms; }
        [class*="st-key-red_black_rank_chart_"] svg g.layer_1_marks :is(path, rect):nth-child(4) { animation-delay: 36ms; }
        [class*="st-key-red_black_rank_chart_"] svg g.layer_1_marks :is(path, rect):nth-child(5) { animation-delay: 48ms; }
        [class*="st-key-red_black_rank_chart_"] svg g.layer_1_marks :is(path, rect):nth-child(n+6) { animation-delay: 60ms; }
        @media (max-width: 860px) {
            .red-black-metric-band { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .red-black-metric-item:nth-child(3) { border-left: 0; }
            .red-black-metric-item:nth-child(n+3) { border-top: 1px solid var(--border); }
        }
        @media (max-width: 520px) {
            .red-black-metric-band { grid-template-columns: 1fr; }
            .red-black-metric-item { min-height: 100px; padding: 14px 12px; }
            .red-black-metric-item + .red-black-metric-item {
                border-top: 1px solid var(--border);
                border-left: 0;
            }
        }
        @media (prefers-reduced-motion: reduce) {
            .red-black-metric-band,
            .red-black-metric-item,
            .red-black-metric-item::after,
            .red-black-metric-label,
            .red-black-metric-value,
            [class*="st-key-red_black_rank_chart_"] .stVegaLiteChart,
            [class*="st-key-red_black_rank_chart_"] svg g.layer_1_marks :is(path, rect) {
                animation: none !important;
                transition: none !important;
            }
            .red-black-metric-band:hover,
            .red-black-metric-item:hover::after,
            .red-black-metric-item:hover .red-black-metric-value,
            [class*="st-key-red_black_rank_chart_"] svg g.layer_1_marks :is(path, rect) {
                transform: none !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _red_black_metric_item(
    label: str,
    value: int | float | str,
    note: str,
    tone: str = "",
) -> str:
    tone_class = f" tone-{escape(tone)}" if tone else ""
    return (
        f'<div class="red-black-metric-item{tone_class}">'
        f'<div class="red-black-metric-label">{escape(label)}</div>'
        f'<div class="red-black-metric-value">{escape(str(value))}</div>'
        f'<div class="red-black-metric-note">{escape(note)}</div>'
        "</div>"
    )


def _render_red_black_metric_band(
    st,
    items: list[tuple[str, int | float | str, str, str]],
) -> None:
    st.markdown(
        '<div class="red-black-metric-band">'
        + "".join(
            _red_black_metric_item(label, value, note, tone)
            for label, value, note, tone in items
        )
        + "</div>",
        unsafe_allow_html=True,
    )


def _render_deviation_chart(st, dataframe: pd.DataFrame, chart_type: str) -> None:
    if dataframe.empty:
        st.info("当前筛选条件下暂无榜单数据。")
        return

    chart_df = dataframe.copy()
    if chart_type == "red":
        x_field = "充值倍率"
        y_field = "角色名"
        color = COLORS["primary"]
        track_color = COLORS["primary_soft"]
        text_format = ".2f"
        title = "充值倍率"
        semantic_field = "红榜评级"
    else:
        x_field = "风险指数"
        y_field = "角色名"
        color = COLORS["accent"]
        track_color = COLORS["surface_muted"]
        text_format = ",.0f"
        title = "风险指数"
        semantic_field = "风险等级"

    chart_df = chart_df.sort_values(x_field, ascending=False).reset_index(drop=True)
    chart_df["_rank"] = range(1, len(chart_df) + 1)
    chart_df["_rank_label"] = [
        f"{rank:02d}  {name}"
        for rank, name in zip(chart_df["_rank"], chart_df[y_field].astype(str), strict=False)
    ]
    maximum = max(float(chart_df[x_field].max()), 1.0)
    chart_maximum = maximum * 1.13
    chart_df["_chart_maximum"] = chart_maximum
    rank_order = chart_df["_rank_label"].tolist()

    y_encoding = alt.Y(
        "_rank_label:N",
        title=None,
        sort=rank_order,
        axis=alt.Axis(
            labelColor=COLORS["text_secondary"],
            labelFontSize=12,
            labelLimit=170,
            labelPadding=12,
            ticks=False,
            domain=False,
        ),
    )
    x_scale = alt.Scale(domain=[0, chart_maximum], nice=False)
    base = alt.Chart(chart_df).encode(y=y_encoding)
    tracks = base.mark_bar(
        size=16,
        cornerRadius=8,
        color=track_color,
    ).encode(
        x=alt.X(
            "_chart_maximum:Q",
            title=title,
            scale=x_scale,
            axis=alt.Axis(
                labelColor=COLORS["text_tertiary"],
                labelFontSize=11,
                labelPadding=8,
                titleColor=COLORS["text_secondary"],
                titleFontSize=12,
                titleFontWeight=600,
                titlePadding=16,
                gridColor=COLORS["border"],
                gridOpacity=0.55,
                tickColor=COLORS["border"],
                domain=False,
                tickCount=6,
            ),
        )
    )
    tooltips = [
        alt.Tooltip("_rank:Q", title="排名", format="d"),
        alt.Tooltip(f"{y_field}:N", title="角色名"),
        alt.Tooltip(f"{x_field}:Q", title=title, format=text_format),
        alt.Tooltip(f"{semantic_field}:N", title=semantic_field),
        alt.Tooltip("区服:N", title="区服"),
        alt.Tooltip("服务器类型:N", title="服务器类型"),
        alt.Tooltip("用户来源:N", title="用户来源"),
        alt.Tooltip("近一周充值:Q", title="近一周充值", format=",.2f"),
        alt.Tooltip("前7日充值:Q", title="前7日充值", format=",.2f"),
        alt.Tooltip("过去28日周均充值:Q", title="过去28日周均", format=",.2f"),
        alt.Tooltip("基准范围:N", title="采用基准"),
        alt.Tooltip("累计充值:Q", title="累计充值", format=",.2f"),
    ]
    if chart_type == "observation":
        tooltips.extend(
            [
                alt.Tooltip("最后登录间隔:Q", title="未登录天数", format="d"),
                alt.Tooltip("观察原因:N", title="观察原因"),
                alt.Tooltip("运营建议:N", title="运营建议"),
            ]
        )
    bars = base.mark_bar(
        size=16,
        cornerRadius=8,
        color=color,
    ).encode(
        x=alt.X(f"{x_field}:Q", scale=x_scale, axis=None),
        opacity=alt.condition(alt.datum._rank <= 3, alt.value(1.0), alt.value(0.76)),
        tooltip=tooltips,
    )
    labels = base.mark_text(
        dx=7,
        align="left",
        baseline="middle",
        color=COLORS["text"],
        fontSize=11,
        fontWeight=600,
    ).encode(
        x=alt.X(f"{x_field}:Q", scale=x_scale, axis=None),
        text=alt.Text(f"{x_field}:Q", format=text_format),
    )
    rank_chart = (
        (tracks + bars + labels)
        .properties(
            height=max(280, len(chart_df) * 29),
            padding={"left": 12, "right": 28, "top": 6, "bottom": 4},
        )
        .configure_view(strokeWidth=0)
    )
    with st.container(key=f"red_black_rank_chart_{chart_type}", border=True):
        st.altair_chart(
            rank_chart,
            use_container_width=True,
        )


def _red_black_column_config(st, dataframe: pd.DataFrame) -> dict[str, object]:
    config: dict[str, object] = {}
    for column in (
        "累计充值",
        "近一周充值",
        "前7日充值",
        "过去28日周均充值",
        "服务器平均充值",
        "分组稳健均值",
        "分组充值P80",
        "分组累计充值P80",
        "高价值门槛",
        "风险指数",
    ):
        if column in dataframe.columns:
            config[column] = st.column_config.NumberColumn(column, format="%.2f", width="medium")
    if "充值倍率" in dataframe.columns:
        config["充值倍率"] = st.column_config.NumberColumn(
            "充值倍率", format="%.2f ×", width="small"
        )
    for column in (
        "偏离率",
        "个人变化率",
        "前7日变化率",
        "低于均值比例",
        "充值下降比例",
    ):
        if column in dataframe.columns:
            config[column] = st.column_config.NumberColumn(column, format="%.1%", width="small")
    return config


def _filtered_active_base(st, active_df: pd.DataFrame) -> pd.DataFrame:
    with st.container(key="vip_filter_drawer_red_black"):
        with st.expander("查看与调整筛选", expanded=False):
            server_options = sorted(active_df["服务器类型"].dropna().astype(str).unique().tolist())
            source_options = sorted(active_df["用户来源"].dropna().astype(str).unique().tolist())
            zone_options = sorted(active_df["区服"].dropna().astype(str).unique().tolist())
            cols = st.columns(3)
            selected_server = compact_multiselect_filter(
                st,
                cols[0],
                "服务器类型",
                server_options,
                "vip_red_black_filter_server_type",
            )
            selected_source = compact_multiselect_filter(
                st,
                cols[1],
                "用户来源",
                source_options,
                "vip_red_black_filter_source",
            )
            selected_zone = compact_multiselect_filter(
                st,
                cols[2],
                "区服",
                zone_options,
                "vip_red_black_filter_zone",
            )
            st.caption("每项均支持多选；清空任一项时，该项会按全部选项处理。")

        filtered_df = active_df[
            active_df["服务器类型"].astype(str).isin(selected_server if selected_server else server_options)
            & active_df["用户来源"].astype(str).isin(selected_source if selected_source else source_options)
            & active_df["区服"].astype(str).isin(selected_zone if selected_zone else zone_options)
        ]
        server_count = len(selected_server) if selected_server else len(server_options)
        source_count = len(selected_source) if selected_source else len(source_options)
        zone_count = len(selected_zone) if selected_zone else len(zone_options)
        st.markdown(
            f"""
            <div class="filter-state-summary">
                <span class="filter-state-label">已应用条件</span>
                <span>服务器类型 {server_count}/{len(server_options)}</span>
                <span>用户来源 {source_count}/{len(source_options)}</span>
                <span>区服 {zone_count}/{len(zone_options)}</span>
                <strong>当前 {len(filtered_df):,} 名玩家</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )
    return filtered_df


def render(st, db_path) -> None:
    _render_chart_motion_css(st)
    source = _current_source(st, db_path)
    if source is None:
        st.warning("暂无 VIP 数据，请先前往“VIP 运营”从 AE 同步或上传 Excel 文件。")
        return

    try:
        workbook = load_current_workbook(st, db_path)
    except Exception as exc:
        st.error(f"处理失败：{exc}")
        return

    initial_board = build_red_black_board(
        workbook.active_df,
        top_n=RED_BLACK_RULES["top_n"],
        calculation_time=workbook.as_of,
    )
    if initial_board["active_df"].empty:
        st.info("当前 VIP 数据暂无可用于红黑榜计算的有效玩家。")
        return

    section(
        st,
        "筛选条件",
        "筛选只改变当前展示名单；全局分组基准固定，不会随筛选重新计算。",
        "filter",
    )
    filtered_base = _filtered_active_base(st, initial_board["active_df"])
    rules = initial_board["rules"]
    top_n = int(rules["top_n"])
    red_df = filter_board_candidates(
        initial_board["red_candidates_df"], filtered_base, top_n=top_n
    )
    black_df = filter_board_candidates(
        initial_board["black_candidates_df"], filtered_base, top_n=top_n
    )
    observation_df = filter_board_candidates(
        initial_board["observation_df"], filtered_base, top_n=top_n
    )

    section(
        st,
        "红黑榜概览",
        f"基于 {len(initial_board['active_df']):,} 名有效玩家计算全局基准；Top {top_n} 仅负责展示。",
        "flame",
    )
    _render_red_black_metric_band(
        st,
        [
            (
                "符合条件总人数",
                initial_board["eligible_count"],
                "红榜与黑榜完整候选人数，不受 Top 15 限制",
                "",
            ),
            (
                "红榜符合人数",
                initial_board["red_eligible_count"],
                "同时通过个人增长、同组分位与绝对门槛",
                "red",
            ),
            (
                "黑榜符合人数",
                initial_board["black_eligible_count"],
                "高价值且相对个人基准出现明显下降",
                "black",
            ),
            (
                "观察期人数",
                initial_board["observation_count"],
                "7 日登录/充值窗口，或历史基线暂不可比",
                "",
            ),
        ],
    )

    red_tab, black_tab, observation_tab = st.tabs(
        [f"红榜 Top {top_n}", f"黑榜 Top {top_n}", "观察期"],
        key="vip_red_black_tabs",
    )
    with red_tab:
        section(
            st,
            "红榜增长名单",
            f"全量符合 {initial_board['red_eligible_count']} 人；当前筛选后展示前 {len(red_df)} 人。",
            "flame",
        )
        _render_deviation_chart(st, red_df, "red")
        red_columns = [
            "排名",
            "角色名",
            "角色ID",
            "区服",
            "服务器类型",
            "用户来源",
            "近一周充值",
            "前7日充值",
            "过去28日周均充值",
            "分组稳健均值",
            "分组充值P80",
            "充值倍率",
            "个人变化率",
            "基准范围",
            "红榜评级",
            "运营建议",
        ]
        red_display = red_df[[column for column in red_columns if column in red_df.columns]]
        st.dataframe(red_display, use_container_width=True, hide_index=True, height=420, column_config=_red_black_column_config(st, red_display))
    with black_tab:
        section(
            st,
            "黑榜风险指数",
            f"全量符合 {initial_board['black_eligible_count']} 人；当前筛选后展示前 {len(black_df)} 人。",
            "alert",
        )
        _render_deviation_chart(st, black_df, "black")
        black_columns = [
            "排名",
            "角色名",
            "角色ID",
            "区服",
            "服务器类型",
            "用户来源",
            "累计充值",
            "高价值门槛",
            "近一周充值",
            "前7日充值",
            "过去28日周均充值",
            "充值下降比例",
            "最后登录间隔",
            "基线类型",
            "零充值信号",
            "风险指数",
            "风险等级",
            "基准范围",
            "运营建议",
        ]
        black_display = black_df[[column for column in black_columns if column in black_df.columns]]
        st.dataframe(black_display, use_container_width=True, hide_index=True, height=420, column_config=_red_black_column_config(st, black_display))
    with observation_tab:
        section(
            st,
            "观察期风险指数",
            f"共 {initial_board['observation_count']} 人进入观察；当前筛选后展示风险指数最高的 {len(observation_df)} 人。",
            "clock",
        )
        _render_deviation_chart(st, observation_df, "observation")
        observation_columns = [
            "排名",
            "角色名",
            "角色ID",
            "区服",
            "服务器类型",
            "用户来源",
            "累计充值",
            "近一周充值",
            "前7日充值",
            "过去28日周均充值",
            "最后登录间隔",
            "基线类型",
            "基准范围",
            "风险指数",
            "风险等级",
            "观察原因",
            "运营建议",
        ]
        observation_display = observation_df[
            [column for column in observation_columns if column in observation_df.columns]
        ]
        if observation_display.empty:
            st.success("当前没有处于观察期的玩家。")
        else:
            with st.expander(
                f"补充明细 · 查看 {len(observation_display)} 名观察期玩家的完整字段",
                expanded=False,
            ):
                st.caption("明细与上方风险指数图使用相同排序，可用于复制角色 ID 或核对充值窗口。")
                st.dataframe(
                    observation_display,
                    use_container_width=True,
                    hide_index=True,
                    height=420,
                    column_config=_red_black_column_config(st, observation_display),
                )

    old_floor = amount_label(float(rules["red_minimum_payment"]["老服"]))
    new_floor = amount_label(float(rules["red_minimum_payment"]["新服"]))
    old_value_floor = amount_label(float(rules["high_value_minimum"]["老服"]))
    new_value_floor = amount_label(float(rules["high_value_minimum"]["新服"]))
    section(st, "计算规则", "第一阶段稳健分组与第二阶段个人趋势已合并到同一套口径。", "check")
    st.markdown(
        f"""
        <div class="report-list-card">
            <div class="report-list-title">规则说明</div>
            <ul class="report-list">
                <li>全局基准：按服务器类型 × 用户来源分组；样本少于 {int(rules['minimum_group_size'])} 人时回退到服务器类型大组，并去掉最高、最低 {float(rules['trim_ratio']):.0%} 后计算稳健均值。</li>
                <li>红榜：近 7 日充值至少达到同组稳健均值 {float(rules['red_group_multiplier']):.1f} 倍和同组 P80，同时相对个人过去 28 日周均增长至少 {float(rules['red_personal_growth_ratio']):.0%}；绝对门槛为老服 {old_floor}、新服 {new_floor}。</li>
                <li>高价值：累计充值达到同组 P80，且不低于老服 {old_value_floor}、新服 {new_value_floor}。</li>
                <li>黑榜：高价值玩家近 7 日充值相对个人过去 28 日周均下降至少 {float(rules['black_personal_decline_ratio']):.0%}；登录在 7 日进入观察、14 日进入高风险、30 日计为退游。</li>
                <li>充值节点：近 7 日为第一观察窗口，近 7 日与前 7 日连续为 0 时按 14 日高风险窗口加权；单个 7 日零充值只作为观察信号。</li>
                <li>观察期：包含充值历史字段缺失、暂无历史基线、7–13 日未登录，或近 7 日未充值但前 7 日仍有充值的玩家；筛选只改变展示，不改变以上全局基准。</li>
                <li>合服口径：{escape(server_merge_summary())}；玩家先归并到当前主区服，再参与分组基准和榜单计算。</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("导出当前红黑榜基础数据", expanded=False):
        render_player_table(st, filtered_base, len(initial_board["active_df"]), "VIP红黑榜基础数据")
