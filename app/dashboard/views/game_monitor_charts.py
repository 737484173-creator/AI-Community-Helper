from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd

from app.dashboard.design_tokens import COLORS


def risk_trend_chart(
    daily: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> alt.Chart:
    """Build the shared-axis risk volume and severity composition chart."""
    levels = ["高风险", "中风险", "低风险"]
    peak_total = int(daily["风险总量"].max()) if not daily.empty else 0
    shared_y_max = max(1, math.ceil(peak_total * 1.12))
    band_gap = max(2, math.ceil(shared_y_max * 0.18))
    line_offset = shared_y_max + band_gap
    chart_y_max = line_offset + shared_y_max
    daily = daily.copy()
    daily["总量绘图值"] = daily["风险总量"] + line_offset
    peak_days = daily[(daily["风险总量"] == peak_total) & (daily["风险总量"] > 0)]
    trend_rows = daily.melt(
        id_vars=[
            "日期",
            "完整日期",
            "风险总量",
            "高风险明细",
            "中风险明细",
            "低风险明细",
        ],
        value_vars=levels,
        var_name="风险等级",
        value_name="数量",
    )
    trend_rows["堆叠顺序"] = trend_rows["风险等级"].map(
        {"低风险": 0, "中风险": 1, "高风险": 2}
    )

    day_count = max((end_date - start_date).days + 1, 1)
    bar_size = 28 if day_count <= 7 else 14 if day_count <= 14 else 9
    tick_values = _risk_date_tick_values(daily)
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
    axis_ticks = band_ticks + [line_offset + value for value in band_ticks]
    full_y_scale = alt.Scale(domain=[0, chart_y_max], nice=False)
    y_axis = alt.Axis(
        title="风险数",
        titleColor=COLORS["text_secondary"],
        titleFontSize=11,
        titleFontWeight=600,
        titlePadding=12,
        values=axis_ticks,
        labelExpr=(
            f"datum.value >= {line_offset} ? "
            f"format(datum.value - {line_offset}, '.0f') : format(datum.value, '.0f')"
        ),
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
    line_y = alt.Y("总量绘图值:Q", scale=full_y_scale, axis=y_axis)
    stack_y = alt.Y("数量:Q", stack="zero", scale=full_y_scale, axis=y_axis)
    hover = alt.selection_point(
        name="game_risk_date_hover",
        fields=["日期"],
        on="pointerover",
        clear="pointerout",
        empty=False,
    )

    axis_carrier = (
        alt.Chart(pd.DataFrame({"轴刻度范围": [0, chart_y_max]}))
        .mark_point(opacity=0)
        .encode(y=alt.Y("轴刻度范围:Q", scale=full_y_scale, axis=y_axis), x=alt.value(0))
    )
    divider = (
        alt.Chart(pd.DataFrame({"分隔位置": [shared_y_max + band_gap / 2]}))
        .mark_rule(
            color=COLORS["border_strong"],
            strokeWidth=1,
            strokeDash=[4, 5],
            opacity=0.8,
        )
        .encode(y=alt.Y("分隔位置:Q", scale=full_y_scale, axis=y_axis))
    )
    bars = (
        alt.Chart(trend_rows)
        .mark_bar(size=bar_size, cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=shared_x,
            y=stack_y,
            color=alt.Color(
                "风险等级:N",
                scale=alt.Scale(
                    domain=levels,
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
    points = (
        alt.Chart(daily[daily["风险总量"] > 0])
        .mark_point(
            stroke=COLORS["primary"],
            filled=True,
            strokeWidth=1.8,
        )
        .encode(
            x=shared_x,
            y=line_y,
            size=alt.condition(hover, alt.value(112), alt.value(30), empty=False),
            fill=alt.condition(
                hover,
                alt.value(COLORS["primary"]),
                alt.value(COLORS["card"]),
                empty=False,
            ),
        )
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
    return alt.layer(
        axis_carrier,
        divider,
        bars,
        line,
        points,
        peak_points,
        hover_rule,
        selector,
    ).properties(height=320)


def _risk_date_tick_values(daily: pd.DataFrame, max_ticks: int = 8) -> list[pd.Timestamp]:
    if daily.empty:
        return []
    total_rows = len(daily)
    tick_count = min(max_ticks, total_rows)
    if tick_count == 1:
        positions = [0]
    else:
        positions = sorted(
            {round(index * (total_rows - 1) / (tick_count - 1)) for index in range(tick_count)}
        )
    return [pd.Timestamp(daily.iloc[position]["日期"]) for position in positions]
