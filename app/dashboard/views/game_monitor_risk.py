from __future__ import annotations

from io import BytesIO
from html import escape
from typing import Iterable, Mapping

import altair as alt
import pandas as pd

from app.dashboard.design_tokens import COLORS


RISK_LEVELS = ("高风险", "中风险", "低风险")


def server_risk_distribution(dataframe: pd.DataFrame, limit: int = 12) -> pd.DataFrame:
    """Aggregate the current risk result by server and severity."""
    columns = ["区服", "风险等级", "风险消息", "区服总量"]
    if dataframe.empty:
        return pd.DataFrame(columns=columns)

    source = dataframe.copy()
    source["区服"] = source.apply(
        lambda row: _server_label(row.get("server_id"), row.get("server_name")), axis=1
    )
    totals = (
        source.groupby("区服", dropna=False)
        .size()
        .rename("区服总量")
        .sort_values(ascending=False)
    )
    selected_servers = totals.head(max(int(limit), 0)).index
    grouped = (
        source[source["区服"].isin(selected_servers)]
        .groupby(["区服", "risk_level"], dropna=False)
        .size()
        .rename("风险消息")
        .reset_index()
        .rename(columns={"risk_level": "风险等级"})
    )
    grouped["区服总量"] = grouped["区服"].map(totals).astype(int)
    grouped["风险消息"] = grouped["风险消息"].astype(int)
    grouped["区服"] = pd.Categorical(
        grouped["区服"], categories=list(selected_servers), ordered=True
    )
    return grouped.sort_values(["区服", "风险等级"]).reset_index(drop=True)[columns]


def server_risk_chart(distribution: pd.DataFrame) -> alt.Chart:
    """Build a stacked, hoverable server distribution chart."""
    order = [str(value) for value in distribution["区服"].drop_duplicates().tolist()]
    hover = alt.selection_point(
        name="game_risk_server_hover",
        fields=["区服", "风险等级"],
        on="pointerover",
        clear="pointerout",
        empty=False,
    )
    return (
        alt.Chart(distribution)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X("风险消息:Q", title=None, stack="zero", axis=alt.Axis(grid=False)),
            y=alt.Y("区服:N", title=None, sort=order),
            color=alt.Color(
                "风险等级:N",
                scale=alt.Scale(
                    domain=list(RISK_LEVELS),
                    range=[COLORS["danger"], COLORS["warning"], COLORS["risk_low"]],
                ),
                legend=None,
            ),
            opacity=alt.condition(hover, alt.value(1), alt.value(0.78), empty=False),
            stroke=alt.condition(
                hover,
                alt.value(COLORS["text"]),
                alt.value("transparent"),
                empty=False,
            ),
            strokeWidth=alt.condition(hover, alt.value(1.2), alt.value(0), empty=False),
            tooltip=[
                "区服:N",
                "风险等级:N",
                alt.Tooltip("风险消息:Q", title="消息数", format=",d"),
                alt.Tooltip("区服总量:Q", title="区服总量", format=",d"),
            ],
        )
        .add_params(hover)
        .properties(height=max(300, min(len(order), 12) * 28))
    )


def player_risk_ranking(
    dataframe: pd.DataFrame,
    profile_rows: Iterable[Mapping[str, object] | object] = (),
    *,
    limit: int = 12,
) -> pd.DataFrame:
    """Rank players from real risk rows and enrich them with the current VIP snapshot."""
    columns = [
        "排名",
        "role_id",
        "角色名",
        "区服",
        "风险消息",
        "高风险消息",
        "脏话消息",
        "活跃天数",
        "最近命中",
        "最后登录",
        "累计充值",
        "近7日充值",
        "服务器类型",
        "用户来源",
    ]
    if dataframe.empty:
        return pd.DataFrame(columns=columns)

    source = dataframe.copy()
    source["日期"] = source["event_time"].dt.normalize()
    source["高风险标记"] = source["risk_level"].eq("高风险").astype(int)
    source["脏话标记"] = source["risk_type"].eq("脏字/攻击").astype(int)
    source["区服"] = source.apply(
        lambda row: _server_label(row.get("server_id"), row.get("server_name")), axis=1
    )
    ranking = (
        source.groupby("role_id", as_index=False, dropna=False)
        .agg(
            区服=("区服", "first"),
            风险消息=("role_id", "size"),
            高风险消息=("高风险标记", "sum"),
            脏话消息=("脏话标记", "sum"),
            活跃天数=("日期", "nunique"),
            最近命中=("event_time", "max"),
        )
        .sort_values(["风险消息", "高风险消息", "最近命中"], ascending=[False, False, False])
        .head(max(int(limit), 0))
        .reset_index(drop=True)
    )

    profiles = _profile_lookup(profile_rows)
    ranking["角色名"] = ranking["role_id"].map(
        lambda value: str(profiles.get(str(value), {}).get("role_name") or "未记录角色名")
    )
    ranking["最后登录"] = ranking["role_id"].map(
        lambda value: profiles.get(str(value), {}).get("last_login_time")
    )
    ranking["累计充值"] = ranking["role_id"].map(
        lambda value: float(profiles.get(str(value), {}).get("total_payment_amount") or 0)
    )
    ranking["近7日充值"] = ranking["role_id"].map(
        lambda value: float(profiles.get(str(value), {}).get("payment_7d_amount") or 0)
    )
    ranking["服务器类型"] = ranking["role_id"].map(
        lambda value: str(profiles.get(str(value), {}).get("server_type") or "未记录")
    )
    ranking["用户来源"] = ranking["role_id"].map(
        lambda value: str(profiles.get(str(value), {}).get("user_source") or "未记录")
    )
    ranking.insert(0, "排名", range(1, len(ranking) + 1))
    return ranking[columns]


def player_ranking_html(ranking: pd.DataFrame, messages: pd.DataFrame, title: str) -> str:
    if ranking.empty:
        return (
            '<div class="game-risk-player-panel">'
            '<div class="game-risk-player-header"><div>'
            f'<div class="game-risk-player-title">{escape(title)}</div>'
            '<div class="game-risk-player-copy">按当前筛选口径统计，点击玩家可查看具体信息。</div>'
            '</div></div><div class="game-risk-player-empty">当前筛选下暂无可排行的玩家。</div></div>'
        )

    maximum = max(int(ranking["风险消息"].max()), 1)
    entries: list[str] = []
    for row_index, row in ranking.iterrows():
        role_id = str(row["role_id"])
        player_messages = messages[messages["role_id"].astype(str).eq(role_id)].head(2)
        samples = "".join(
            '<div class="game-risk-player-sample">'
            f'<span>{escape(str(item.get("risk_type") or "风险言论"))} · '
            f'{escape(_format_time(item.get("event_time")))}</span>'
            f'<p>{escape(_truncate(item.get("chat_content"), 150))}</p>'
            '</div>'
            for _, item in player_messages.iterrows()
        ) or '<div class="game-risk-player-no-sample">当前筛选下没有可展示的消息样本。</div>'
        width = max(4.0, min(int(row["风险消息"]) / maximum * 100, 100.0))
        top_class = " top-three" if int(row["排名"]) <= 3 else ""
        entries.append(
            f'<details class="game-risk-player-entry{top_class}" style="--row-index:{row_index};--bar-width:{width:.1f}%">'
            '<summary class="game-risk-player-row">'
            f'<span class="game-risk-player-rank">{int(row["排名"]):02d}</span>'
            '<div class="game-risk-player-identity">'
            f'<strong>{escape(str(row["角色名"]))}<em>点击查看</em></strong>'
            f'<span>{escape(str(row["区服"]))} · ID {escape(role_id)}</span></div>'
            f'<strong class="game-risk-player-count">{int(row["风险消息"]):,}</strong>'
            f'<span class="game-risk-player-high">高风险 {int(row["高风险消息"]):,}</span>'
            '<span class="game-risk-player-progress"><span></span></span>'
            '</summary><div class="game-risk-player-detail">'
            f'{_detail_item("角色 ID · 可复制", role_id, code=True)}'
            f'{_detail_item("区服", row["区服"])}'
            f'{_detail_item("风险消息", f"{int(row["风险消息"]):,} 条")}'
            f'{_detail_item("脏话/攻击", f"{int(row["脏话消息"]):,} 条")}'
            f'{_detail_item("活跃天数", f"{int(row["活跃天数"]):,} 天")}'
            f'{_detail_item("最近命中", _format_time(row["最近命中"]))}'
            f'{_detail_item("最后登录", _format_time(row["最后登录"]))}'
            f'{_detail_item("累计充值", f"{float(row["累计充值"]):,.2f}")}'
            f'{_detail_item("近 7 日充值", f"{float(row["近7日充值"]):,.2f}")}'
            f'{_detail_item("服务器类型 / 来源", f"{row["服务器类型"]} · {row["用户来源"]}")}'
            f'<div class="game-risk-player-samples"><span>最近命中样本</span>{samples}</div>'
            '</div></details>'
        )

    return (
        '<div class="game-risk-player-panel">'
        '<div class="game-risk-player-header"><div>'
        f'<div class="game-risk-player-title">{escape(title)}</div>'
        '<div class="game-risk-player-copy">横条表示相对消息量；点击玩家展开真实画像与最近命中样本。</div>'
        f'</div><span>{len(ranking)} 名玩家</span></div>'
        '<div class="game-risk-player-table-head"><span>#</span><span>玩家 / 区服</span>'
        '<span>消息</span><span>风险构成</span></div>'
        f'<div class="game-risk-player-list">{"".join(entries)}</div></div>'
    )


def risk_export_frame(
    dataframe: pd.DataFrame,
    profile_rows: Iterable[Mapping[str, object] | object] = (),
) -> pd.DataFrame:
    profiles = _profile_lookup(profile_rows)
    return pd.DataFrame(
        {
            "风险等级": dataframe["risk_level"],
            "风险类型": dataframe["risk_type"],
            "消息原文": dataframe["chat_content"],
            "判定原因 / 命中规则": dataframe["risk_reason"],
            "角色ID": dataframe["role_id"].astype(str),
            "角色名": dataframe["role_id"].astype(str).map(
                lambda value: profiles.get(value, {}).get("role_name") or ""
            ),
            "区服": dataframe.apply(
                lambda row: _server_label(row.get("server_id"), row.get("server_name")), axis=1
            ),
            "发送时间": dataframe["event_time"].dt.strftime("%Y/%m/%d %H:%M:%S"),
        }
    )


def risk_excel_bytes(dataframe: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="风险言论明细")
    return output.getvalue()


def _profile_lookup(
    profile_rows: Iterable[Mapping[str, object] | object],
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for row in profile_rows:
        try:
            record = dict(row)
        except (TypeError, ValueError):
            continue
        role_id = str(record.get("role_id") or "").strip()
        if role_id:
            result[role_id] = record
    return result


def _server_label(server_id: object, server_name: object) -> str:
    identifier = str(server_id or "").strip()
    name = str(server_name or "").strip()
    if name and identifier and name.casefold() not in {identifier.casefold(), f"s{identifier}".casefold()}:
        return f"{name}（{identifier}）"
    return name or (f"S{identifier}" if identifier else "未知区服")


def _detail_item(label: str, value: object, *, code: bool = False) -> str:
    tag = "code" if code else "strong"
    return (
        '<div class="game-risk-player-detail-item">'
        f'<span>{escape(label)}</span><{tag}>{escape(str(value or "未记录"))}</{tag}></div>'
    )


def _format_time(value: object) -> str:
    if value is None or pd.isna(value):
        return "未记录"
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.strftime("%Y/%m/%d %H:%M")


def _truncate(value: object, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[: limit - 1]}…"
