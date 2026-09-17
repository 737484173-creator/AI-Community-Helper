from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd

from app.database.repositories.vip_ae_repository import AEVIPSnapshotRepository
from app.dashboard.views.vip_common import section
from app.vip.ae_sync import DEFAULT_AE_PROJECT_ID
from app.vip.profile import (
    ProfileInsight,
    build_profile_insight,
    cultivation_progress,
    payment_direction,
    player_option_label,
    recommendation_state,
    server_stage,
)


def _inject_styles(st) -> None:
    css = Path(__file__).with_name("vip_profile.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _safe_number(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if pd.isna(parsed) else parsed


def _safe_text(value: object, fallback: str = "-") -> str:
    if value is None or pd.isna(value):
        return fallback
    text = str(value).strip()
    return text or fallback


def _player_candidates(dataframe: pd.DataFrame, query: str, server_filter: str) -> pd.DataFrame:
    output = dataframe.copy()
    if server_filter != "全部区服":
        output = output[output["区服"].astype(str).eq(server_filter)]
    keyword = query.strip().casefold()
    if keyword:
        role_name = output.get("角色名", pd.Series("", index=output.index)).fillna("").astype(str).str.casefold()
        role_id = output.get("角色ID", pd.Series("", index=output.index)).fillna("").astype(str).str.casefold()
        output = output[role_name.str.contains(keyword, regex=False) | role_id.str.contains(keyword, regex=False)]
    return output.sort_values(["累计充值", "角色ID"], ascending=[False, True], kind="stable")


def _render_selector(st, dataframe: pd.DataFrame) -> pd.Series | None:
    servers = sorted(dataframe["区服"].dropna().astype(str).unique().tolist(), key=lambda value: (len(value), value))
    columns = st.columns([1.15, 0.85, 2.1], vertical_alignment="bottom")
    query = columns[0].text_input(
        "搜索角色",
        placeholder="角色名或角色 ID",
        key="vip_profile_search",
    )
    server_filter = columns[1].selectbox(
        "区服",
        options=["全部区服", *servers],
        key="vip_profile_server",
    )
    candidates = _player_candidates(dataframe, query, server_filter)
    if candidates.empty:
        columns[2].selectbox("画像对象", options=["没有匹配玩家"], disabled=True)
        st.info("当前筛选条件下没有匹配的有效 VIP 玩家。")
        return None

    options = list(candidates.index)
    selected_index = columns[2].selectbox(
        "画像对象",
        options=options,
        format_func=lambda index: player_option_label(candidates.loc[index]),
        key="vip_profile_player_index",
    )
    return candidates.loc[selected_index]


def _render_hero(
    st,
    player: pd.Series,
    insight: ProfileInsight,
    as_of: datetime | None,
) -> None:
    verdict, verdict_copy, tone = recommendation_state(insight.coverage, insight)
    stage = server_stage(player.get("区服"), as_of=as_of)
    role_name = _safe_text(player.get("角色名"), "未命名玩家")
    role_id = _safe_text(player.get("角色ID"))
    group = _safe_text(player.get("玩家分组"), "未分类")
    source = _safe_text(player.get("用户来源"), "未知来源")
    stage_copy = "全部养成线已开放" if stage.fully_unlocked else (
        f"开服第 {stage.age_days} 天" if stage.age_days is not None else "开服时间待补齐"
    )
    st.markdown(
        f"""
        <div class="vip-profile-hero">
            <div class="vip-profile-identity">
                <div class="vip-profile-eyebrow">VIP PLAYER PROFILE</div>
                <div class="vip-profile-name-row">
                    <div class="vip-profile-name">{escape(role_name)}</div>
                    <span class="vip-profile-chip">{escape(stage.label)}</span>
                    <span class="vip-profile-chip">{escape(group)}</span>
                </div>
                <div class="vip-profile-meta">
                    <span>角色 ID <code>{escape(role_id)}</code></span>
                    <span>{escape(source)}</span>
                    <span>{escape(stage_copy)}</span>
                </div>
            </div>
            <div class="vip-profile-verdict {escape(tone)}">
                <span class="vip-profile-verdict-label">当前需求判断</span>
                <strong>{escape(verdict)}</strong>
                <p>{escape(verdict_copy)}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_metrics(st, player: pd.Series) -> None:
    payment_label, payment_note = payment_direction(player)
    last_login = player.get("最后登录时间")
    if pd.isna(last_login):
        login_label = "-"
    else:
        login_label = pd.Timestamp(last_login).strftime("%Y/%m/%d")
    metrics = [
        ("累计充值", f"{_safe_number(player.get('累计充值')):,.2f}", "美元口径"),
        ("近 7 日充值", f"{_safe_number(player.get('近一周充值')):,.2f}", payment_label),
        ("前 7 日充值", f"{_safe_number(player.get('前7日充值')):,.2f}", payment_note),
        ("最后登录", login_label, _safe_text(player.get("触达优先级"), "暂无优先级")),
    ]
    html = "".join(
        f'<div class="vip-profile-metric"><span>{escape(label)}</span><strong>{escape(value)}</strong><em>{escape(note)}</em></div>'
        for label, value, note in metrics
    )
    st.markdown(f'<div class="vip-profile-metrics">{html}</div>', unsafe_allow_html=True)


def _render_recommendations(st, insight: ProfileInsight) -> None:
    if not insight.recommendations:
        st.markdown(
            '<div class="vip-profile-panel"><div class="vip-profile-panel-head">'
            '<div><strong>需求方向</strong><br><span>综合购买偏好、战力缺口与养成阶段</span></div>'
            '<span>待同步</span></div><div class="vip-profile-empty"><div>'
            '<strong>暂不输出具体消费方向</strong>'
            '<p>需要同时具备 role_pay 礼包明细与玩家分项战力；缺失任一来源时不会使用推测结果。</p>'
            '</div></div></div>',
            unsafe_allow_html=True,
        )
        return
    cards: list[str] = []
    for index, signal in enumerate(insight.recommendations, start=1):
        examples = "、".join((*signal.packages[:2], *signal.items[:2])) or "暂无可展示名称"
        gap_copy = f"分项缺口 {signal.gap_ratio:.0%}" if signal.gap_ratio > 0 else "分项接近同阶段基准"
        cards.append(
            f'<div class="vip-demand-card{" primary" if index == 1 else ""}">'
            f'<div class="vip-demand-rank">0{index}</div><div class="vip-demand-main">'
            f'<strong>{escape(signal.category)}</strong><span>{escape(examples)}</span>'
            f'<div class="vip-demand-track"><i style="width:{min(signal.score, 100):.1f}%"></i></div>'
            '</div><div class="vip-demand-evidence">'
            f'<b>{signal.score:.0f}</b><span>需求方向指数</span>'
            f'<em>近30日 {signal.recent_amount:,.2f} · {escape(gap_copy)}</em></div></div>'
        )
    st.markdown(
        '<div class="vip-profile-panel vip-demand-panel"><div class="vip-profile-panel-head">'
        '<div><strong>需求方向</strong><br><span>55% 购买偏好 + 35% 同阶段战力缺口 + 10% 解锁阶段</span></div>'
        f'<span>置信度 {escape(insight.confidence)}</span></div>'
        f'<div class="vip-demand-list">{"".join(cards)}</div></div>',
        unsafe_allow_html=True,
    )


def _render_purchase_panel(st, purchase_rows: pd.DataFrame) -> None:
    if purchase_rows.empty:
        st.markdown(
            '<div class="vip-profile-panel"><div class="vip-profile-panel-head">'
            '<div><strong>礼包与道具偏好</strong><br><span>基于 role_pay 的真实购买内容</span></div>'
            '<span>待同步</span></div><div class="vip-profile-empty"><div>'
            '<strong>购买明细尚未写入本地画像快照</strong>'
            '<p>同步成功后展示礼包、道具、购买次数和实付金额。</p>'
            '</div></div></div>',
            unsafe_allow_html=True,
        )
        return
    lifetime = purchase_rows[purchase_rows["window_key"].astype(str).eq("lifetime")].copy()
    lifetime["payment_amount"] = pd.to_numeric(lifetime["payment_amount"], errors="coerce").fillna(0)
    lifetime["purchase_count"] = pd.to_numeric(lifetime["purchase_count"], errors="coerce").fillna(0)
    ranked = lifetime.sort_values(
        ["payment_amount", "purchase_count"],
        ascending=[False, False],
        kind="stable",
    ).head(5)
    maximum = max(float(ranked["payment_amount"].max()) if not ranked.empty else 0.0, 1.0)
    rows: list[str] = []
    for _, item in ranked.iterrows():
        amount = float(item["payment_amount"])
        width = 100 * amount / maximum
        rows.append(
            '<div class="vip-purchase-row"><div>'
            f'<strong>{escape(_safe_text(item.get("giftbox_name"), "未命名礼包"))}</strong>'
            f'<span>{escape(_safe_text(item.get("category"), "其他"))} · {int(item["purchase_count"]):,} 次</span>'
            f'<div class="vip-purchase-track"><i style="width:{width:.1f}%"></i></div></div>'
            f'<b>{amount:,.2f}</b></div>'
        )
    window_label = _safe_text(lifetime.iloc[0].get("window_label"), "历史累计") if not lifetime.empty else "历史累计"
    st.markdown(
        '<div class="vip-profile-panel"><div class="vip-profile-panel-head">'
        '<div><strong>礼包与道具偏好</strong><br><span>按礼包实付金额排序，不重复累计礼包内道具</span></div>'
        f'<span>{escape(window_label)}</span></div><div class="vip-profile-list">'
        f'{"".join(rows) if rows else "<div class=\"vip-profile-empty\"><div><strong>暂无购买记录</strong></div></div>"}'
        '</div></div>',
        unsafe_allow_html=True,
    )


def _render_power_gap_panel(st, insight: ProfileInsight) -> None:
    gaps = insight.power_gaps[:5]
    if not gaps:
        st.markdown(
            '<div class="vip-profile-panel"><div class="vip-profile-panel-head">'
            '<div><strong>分项战力缺口</strong><br><span>与同养成阶段 VIP 中位水平比较</span></div>'
            '<span>无可用差距</span></div><div class="vip-profile-empty"><div>'
            '<strong>分项战力不足或未同步</strong><p>不会把缺失值当作真实低战力。</p>'
            '</div></div></div>',
            unsafe_allow_html=True,
        )
        return
    rows = "".join(
        '<div class="vip-gap-row"><div>'
        f'<strong>{escape(gap.label)}</strong><span>同阶段样本 {gap.peer_count} 人</span>'
        f'<div class="vip-gap-track"><i style="width:{gap.gap_ratio * 100:.1f}%"></i></div></div>'
        f'<b>{gap.gap_ratio:.0%}</b></div>'
        for gap in gaps
    )
    st.markdown(
        '<div class="vip-profile-panel"><div class="vip-profile-panel-head">'
        '<div><strong>分项战力缺口</strong><br><span>按分项占总战力比例，与同阶段 VIP 中位数比较</span></div>'
        f'<span>{len(gaps)} 个明显缺口</span></div><div class="vip-profile-list">{rows}</div></div>',
        unsafe_allow_html=True,
    )


def _render_stage_panel(st, player: pd.Series, as_of: datetime | None) -> None:
    unlocked, upcoming, conditional = cultivation_progress(player.get("区服"), as_of=as_of)
    rows: list[str] = []
    for item in upcoming[:5]:
        rows.append(
            '<div class="vip-profile-row"><div>'
            f'<strong>{escape(str(item["name"]))}</strong>'
            f'<span>{escape(str(item.get("requirement") or ""))}</span></div>'
            f'<b class="upcoming">{int(item.get("days_remaining") or 0)} 天后</b></div>'
        )
    if not rows:
        for item in unlocked[-5:]:
            rows.append(
                '<div class="vip-profile-row"><div>'
                f'<strong>{escape(str(item["name"]))}</strong>'
                f'<span>{escape(str(item.get("requirement") or ""))}</span></div>'
                '<b class="ready">已开放</b></div>'
            )
    count_copy = f"已开放 {len(unlocked)} · 待开放 {len(upcoming)} · 前置条件 {len(conditional)}"
    st.markdown(
        '<div class="vip-profile-panel">'
        '<div class="vip-profile-panel-head"><div><strong>养成阶段</strong><br>'
        '<span>按主服开服时间与新版天数计算</span></div>'
        f'<span>{escape(count_copy)}</span></div>'
        f'<div class="vip-profile-list">{"".join(rows)}</div></div>',
        unsafe_allow_html=True,
    )


def _render_coverage_panel(st, insight: ProfileInsight) -> None:
    coverage = insight.coverage
    items = [
        ("充值节奏", coverage.recharge, "当前快照"),
        ("礼包购买", coverage.purchases, "role_pay 明细"),
        ("分项战力", coverage.power, "玩家属性"),
    ]
    cards = "".join(
        f'<div class="vip-coverage-item{" available" if available else ""}">'
        f'<span>{escape(source)}</span><strong>{escape(label)} · {"可用" if available else "待同步"}</strong></div>'
        for label, available, source in items
    )
    st.markdown(
        '<div class="vip-profile-panel">'
        '<div class="vip-profile-panel-head"><div><strong>画像证据覆盖</strong><br>'
        '<span>只有真实数据完整时才输出具体需求方向</span></div>'
        f'<span>{coverage.available_count} / {coverage.total_count}</span></div>'
        f'<div class="vip-coverage">{cards}</div></div>',
        unsafe_allow_html=True,
    )


def _load_purchase_rows(db_path, workbook, role_id: str) -> pd.DataFrame:
    sheet_names = tuple(getattr(getattr(workbook, "report", None), "sheet_names", ()))
    if db_path is None or not any(str(name).startswith("AE项目") for name in sheet_names):
        return pd.DataFrame()
    rows = AEVIPSnapshotRepository(db_path).list_purchase_packages(
        DEFAULT_AE_PROJECT_ID,
        role_id,
    )
    return pd.DataFrame([dict(row) for row in rows]) if rows else pd.DataFrame()


def render(st, workbook, db_path=None) -> None:
    _inject_styles(st)
    section(
        st,
        "VIP 用户画像",
        "结合真实付费、礼包偏好、分项战力和养成阶段，判断玩家当前最可能消费的内容。",
        "users",
    )
    as_of = getattr(workbook, "as_of", None)
    as_of_label = as_of.strftime("%Y/%m/%d %H:%M") if isinstance(as_of, datetime) else "当前数据源"
    st.markdown(
        f'<div class="vip-profile-context"><span>画像基准 <strong>{escape(as_of_label)}</strong></span>'
        '<span>退款、撤销、礼包关闭、结算发起、库存与资源余额均不计入</span></div>',
        unsafe_allow_html=True,
    )
    player = _render_selector(st, workbook.active_df)
    if player is None:
        return
    role_id = _safe_text(player.get("角色ID"), "")
    purchase_rows = _load_purchase_rows(db_path, workbook, role_id)
    insight = build_profile_insight(
        player,
        purchase_rows,
        workbook.active_df,
        as_of=as_of,
    )
    _render_hero(st, player, insight, as_of)
    _render_metrics(st, player)
    _render_recommendations(st, insight)
    columns = st.columns([1.05, 0.95], gap="large")
    with columns[0]:
        _render_purchase_panel(st, purchase_rows)
    with columns[1]:
        _render_power_gap_panel(st, insight)
    lower_columns = st.columns([1.05, 0.95], gap="large")
    with lower_columns[0]:
        _render_stage_panel(st, player, as_of)
    with lower_columns[1]:
        _render_coverage_panel(st, insight)
