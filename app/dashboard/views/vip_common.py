from __future__ import annotations

from datetime import datetime
from html import escape

import pandas as pd

from app.dashboard.styles import icon_svg
from app.vip.service import dataframe_to_excel_bytes
from app.vip.utils.excel_reader import REQUIRED_FIELDS


def amount_label(value: float) -> str:
    return f"{float(value):,.2f}"


def section(st, title: str, caption: str, icon_name: str) -> None:
    st.markdown(
        f"""
        <div class="workbench-strip">
            <div>
                <div class="workbench-title">{icon_svg(icon_name)} {escape(title)}</div>
                <div class="workbench-subtitle">{escape(caption)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: int | float | str, note: str = "") -> str:
    return (
        '<div class="dashboard-card"><div class="dashboard-top"><div>'
        f'<div class="metric-label">{escape(str(label))}</div>'
        f'<div class="dashboard-number">{escape(str(value))}</div>'
        f'<div class="metric-note">{escape(str(note))}</div>'
        f'</div><div class="icon-box">{icon_svg("users")}</div></div></div>'
    )


def render_metric_grid(st, cards: list[str]) -> None:
    st.markdown(
        f'<div class="aidc-metric-grid">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def compact_multiselect_filter(
    st,
    host,
    label: str,
    options: list[str],
    key: str,
) -> list[str]:
    """Render a multi-select inside a compact popover trigger."""
    stored_values = st.session_state.get(key)
    if stored_values is None:
        st.session_state[key] = list(options)
    else:
        valid_values = [value for value in stored_values if value in options]
        if list(stored_values) != valid_values:
            st.session_state[key] = valid_values

    selected_count = len(st.session_state[key]) if st.session_state[key] else len(options)
    status = "全部" if selected_count == len(options) else f"{selected_count}/{len(options)}"
    with host.popover(f"{label} · {status}", use_container_width=True):
        st.markdown(f"**{label}**")
        st.caption(f"支持多选，共 {len(options)} 项；清空时按全部处理。")
        selected = st.multiselect(
            label,
            options,
            key=key,
            label_visibility="collapsed",
        )
    return list(selected)


def visible_required_fields() -> list[str]:
    return [field for field in REQUIRED_FIELDS if field != "DC是否建联"]


def recognition_records(matched_columns: dict[str, str | None], missing_fields: list[str]) -> list[dict]:
    visible_missing = [field for field in missing_fields if field != "DC是否建联"]
    records = []
    for field in visible_required_fields():
        matched_column = matched_columns.get(field)
        if matched_column:
            status = "已识别"
            source = matched_column
        elif field not in visible_missing:
            status = "规则补齐"
            source = "未识别，已由系统规则补齐"
        else:
            status = "未识别"
            source = "未识别"
        records.append(
            {
                "标准字段": field,
                "匹配到的 Excel 列": source,
                "状态": status,
            }
        )
    return records


def player_column_config(st, dataframe: pd.DataFrame) -> dict[str, object]:
    config: dict[str, object] = {}
    for column in ("累计充值", "近一周充值"):
        if column in dataframe.columns:
            config[column] = st.column_config.NumberColumn(column, format="%.2f", width="medium")
    for column in ("价值分", "风险分"):
        if column in dataframe.columns:
            config[column] = st.column_config.NumberColumn(column, format="%d", width="small")
    if "最后登录时间" in dataframe.columns:
        config["最后登录时间"] = st.column_config.DatetimeColumn("最后登录时间", width="medium")
    if "触达优先级" in dataframe.columns:
        config["触达优先级"] = st.column_config.TextColumn("触达优先级", width="medium")
    if "原因" in dataframe.columns:
        config["原因"] = st.column_config.TextColumn("原因", width="large")
    return config


def render_player_table(st, dataframe: pd.DataFrame, total_count: int, file_prefix: str) -> None:
    with st.container(border=True):
        toolbar_cols = st.columns([1, 0.32])
        toolbar_cols[0].markdown(
            f"**玩家明细**  当前显示 {len(dataframe):,} / {total_count:,} 名玩家"
        )
        toolbar_cols[1].download_button(
            "导出 Excel",
            data=dataframe_to_excel_bytes(dataframe),
            file_name=f"{file_prefix}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        st.dataframe(
            dataframe,
            use_container_width=True,
            hide_index=True,
            height=520,
            column_config=player_column_config(st, dataframe),
        )
