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
    giftbox_display_name,
    infer_package_price_tiers,
    normalize_purchase_rows,
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


def _safe_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "none", "null"}
    return bool(value)


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
            '<p>需要具备 role_pay 或龙币 Item 消费明细，并同时具备分项战力；缺失时不会使用推测结果。</p>'
            '</div></div></div>',
            unsafe_allow_html=True,
        )
        return
    cards: list[str] = []
    for index, signal in enumerate(insight.recommendations, start=1):
        examples = "、".join(signal.packages[:3]) or "礼包名称待补齐"
        gap_copy = f"分项缺口 {signal.gap_ratio:.0%}" if signal.gap_ratio > 0 else "分项接近同阶段基准"
        recent_copy = (
            f"档位累计 ${signal.recent_amount:,.2f}"
            if signal.recent_amount > 0
            else "暂无近 30 日消费"
        )
        cards.append(
            f'<div class="vip-demand-card{" primary" if index == 1 else ""}">'
            f'<div class="vip-demand-rank">0{index}</div><div class="vip-demand-main">'
            f'<strong>{escape(signal.category)}</strong><span>{escape(examples)}</span>'
            f'<div class="vip-demand-track"><i style="width:{min(signal.score, 100):.1f}%"></i></div>'
            '</div><div class="vip-demand-evidence">'
            f'<b>{signal.score:.0f}</b><span>需求方向指数</span>'
            f'<em>近30日 {escape(recent_copy)} · {escape(gap_copy)}</em></div></div>'
        )
    st.markdown(
        '<div class="vip-profile-panel vip-demand-panel"><div class="vip-profile-panel-head">'
        '<div><strong>需求方向</strong><br><span>55% 礼包名与档位偏好 + 35% VIP 榜单战力缺口 + 10% 解锁阶段</span></div>'
        f'<span>置信度 {escape(insight.confidence)}</span></div>'
        f'<div class="vip-demand-list">{"".join(cards)}</div></div>',
        unsafe_allow_html=True,
    )


def _render_purchase_panel(
    st,
    purchase_rows: pd.DataFrame,
    price_tiers: dict[str, float],
    window_status: dict[str, str],
) -> None:
    selected_range = st.segmented_control(
        "礼包偏好时间",
        options=("近7天", "近14天", "总览"),
        default="总览",
        key="vip_profile_purchase_range",
    ) or "总览"
    window_key = {
        "近7天": "recent_7d",
        "近14天": "recent_14d",
        "总览": "lifetime",
    }[selected_range]
    if purchase_rows.empty:
        st.markdown(
            '<div class="vip-profile-panel"><div class="vip-profile-panel-head">'
            '<div><strong>礼包偏好</strong><br><span>按礼包名归类，按标准档位 × 购买次数累计</span></div>'
            '<span>待同步</span></div><div class="vip-profile-empty"><div>'
            '<strong>购买明细尚未写入本地画像快照</strong>'
            '<p>同步成功后将不同支付方式合并到同一礼包档位。</p>'
            '</div></div></div>',
            unsafe_allow_html=True,
        )
        return
    if window_key != "lifetime" and not window_status.get(window_key):
        st.markdown(
            '<div class="vip-profile-panel"><div class="vip-profile-panel-head">'
            f'<div><strong>礼包偏好 · {escape(selected_range)}</strong><br>'
            '<span>该窗口需要独立的 AE 汇总，不能从 30 天合计反推</span></div>'
            '<span>待同步</span></div><div class="vip-profile-empty"><div>'
            '<strong>该时间窗口尚未同步</strong>'
            '<p>请执行一次“同步 AE 数据”；同步完成后将展示真实的礼包购买次数与档位累计。</p>'
            '</div></div></div>',
            unsafe_allow_html=True,
        )
        return
    purchase_rows = normalize_purchase_rows(purchase_rows, price_tiers=price_tiers)
    selected_rows = purchase_rows[
        purchase_rows["window_key"].astype(str).eq(window_key)
    ].copy()
    if selected_rows.empty:
        st.markdown(
            '<div class="vip-profile-panel"><div class="vip-profile-panel-head">'
            f'<div><strong>礼包偏好 · {escape(selected_range)}</strong><br>'
            '<span>现金与龙币购买合并到同一礼包档位</span></div>'
            f'<span>{escape(window_status.get(window_key) or selected_range)}</span></div>'
            '<div class="vip-profile-empty"><div><strong>该时间范围没有匹配到礼包购买</strong>'
            '<p>数据窗口已成功加载，这代表该玩家在所选时间内没有可归因的礼包记录。</p>'
            '</div></div></div>',
            unsafe_allow_html=True,
        )
        return
    if "payment_channel" not in selected_rows.columns:
        selected_rows["payment_channel"] = "cash"
    if "currency_name" not in selected_rows.columns:
        selected_rows["currency_name"] = "美元"
    if "is_demand_evidence" not in selected_rows.columns:
        selected_rows["is_demand_evidence"] = True
    selected_rows["payment_amount"] = pd.to_numeric(selected_rows["payment_amount"], errors="coerce").fillna(0)
    selected_rows["purchase_count"] = pd.to_numeric(selected_rows["purchase_count"], errors="coerce").fillna(0)
    selected_rows["is_demand_evidence"] = selected_rows["is_demand_evidence"].map(_safe_bool)
    unmatched_coin = float(
        selected_rows.loc[
            selected_rows["payment_channel"].eq("dragon_coin")
            & ~selected_rows["is_demand_evidence"],
            "payment_amount",
        ].sum()
    )
    coin_funding = selected_rows[
        selected_rows["payment_channel"].eq("cash")
        & selected_rows["category"].eq("龙币充值")
    ].copy()
    evidence = selected_rows[selected_rows["is_demand_evidence"]].copy()
    evidence["display_name"] = evidence.apply(
        lambda item: giftbox_display_name(
            item.get("giftbox_name"), item.get("giftbox_id")
        )[0],
        axis=1,
    )
    evidence["display_id"] = (
        evidence["giftbox_id"]
        .fillna("")
        .astype(str)
        .str.removeprefix("dragon_coin:")
        .str.split("::", n=1)
        .str[0]
    )
    ranked = (
        evidence.groupby(
            ["display_name", "display_id", "category", "price_tier"],
            dropna=False,
            as_index=False,
        )
        .agg(purchase_count=("purchase_count", "sum"), tier_spend=("tier_spend", "sum"))
        .sort_values(
            ["tier_spend", "purchase_count"],
            ascending=[False, False],
            kind="stable",
        )
        .head(6)
    )
    maximum_spend = max(float(ranked["tier_spend"].max()), 1.0) if not ranked.empty else 1.0
    rows: list[str] = []
    for _, item in ranked.iterrows():
        tier = float(item["price_tier"])
        tier_spend = float(item["tier_spend"])
        width = 100 * tier_spend / maximum_spend
        giftbox_name = str(item["display_name"])
        tier_copy = f"${tier:,.2f} 档" if tier > 0 else "档位待匹配"
        amount_label = f"${tier_spend:,.2f}" if tier > 0 else "—"
        rows.append(
            '<div class="vip-purchase-row"><div>'
            '<div class="vip-purchase-title">'
            f'<strong>{escape(giftbox_name)}</strong>'
            f'</div>'
            f'<span>{escape(_safe_text(item.get("category"), "其他"))} · {int(item["purchase_count"]):,} 次'
            f' · {escape(tier_copy)} · ID {escape(str(item.get("display_id") or "-"))}</span>'
            f'<div class="vip-purchase-track"><i style="width:{width:.1f}%"></i></div></div>'
            f'<b>{escape(amount_label)}<small>档位累计</small></b></div>'
        )
    window_label = _safe_text(
        window_status.get(window_key)
        or selected_rows.iloc[0].get("window_label"),
        "历史累计" if window_key == "lifetime" else selected_range,
    )
    unmatched_note = (
        f'<div class="vip-purchase-note">另有 {unmatched_coin:,.0f} 龙币已消耗，但未唯一匹配到礼包奖励，未进入需求评分。</div>'
        if unmatched_coin > 0
        else ""
    )
    funding_note = ""
    if not coin_funding.empty:
        funding_names = []
        for value in coin_funding["giftbox_name"].astype(str):
            if value and value not in funding_names:
                funding_names.append(value)
        funding_note = (
            '<div class="vip-purchase-note">'
            f'现金购入龙币 ${coin_funding["payment_amount"].sum():,.2f}，'
            f'共 {int(round(coin_funding["purchase_count"].sum())):,} 次；'
            f'档位：{escape("、".join(funding_names[:6]))}。'
            '购入龙币本身不代表具体养成需求，因此不重复计入礼包方向。'
            '</div>'
        )
    cash_tier_total = float(
        evidence.loc[evidence["payment_channel"].eq("cash"), "tier_spend"].sum()
    )
    fallback_tier_count = int(evidence["price_tier_source"].eq("当前记录均价").sum())
    unmapped_tier_count = int(evidence["price_tier_source"].eq("档位待匹配").sum())
    exception_copy = ""
    if fallback_tier_count:
        exception_copy += f' 其中 {fallback_tier_count} 条未形成榜单众数，暂用该记录的平均单价。'
    if unmapped_tier_count:
        exception_copy += f' 另有 {unmapped_tier_count} 条龙币记录尚未匹配到同款现金档位，不计金额权重。'
    methodology_note = (
        '<div class="vip-purchase-note">'
        '<strong>档位计算：</strong>同一礼包取 VIP 榜单历史现金订单中最常出现的标准单价；'
        '档位累计 = 标准档位 × 购买次数，例如 $19.99 × 3 次 = $59.97。'
        f'当前现金订单按档位累计 ${cash_tier_total:,.2f}；龙币支付匹配到同款礼包后合并计算需求，'
        f'但不会伪装成现金实付。{escape(exception_copy)}'
        '</div>'
    )
    st.markdown(
        '<div class="vip-profile-panel"><div class="vip-profile-panel-head">'
        f'<div><strong>礼包偏好 · {escape(selected_range)}</strong><br><span>现金与龙币购买合并到礼包档位；需求分类只看礼包名，不读取次要道具</span></div>'
        f'<span>{escape(window_label)}</span></div><div class="vip-profile-list">'
        f'{"".join(rows) if rows else "<div class=\"vip-profile-empty\"><div><strong>暂无可归因的消费记录</strong></div></div>"}'
        f'{methodology_note}{funding_note}{unmatched_note}</div></div>',
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
        f'<strong>{escape(gap.label)}</strong><span>{escape(gap.peer_basis)} · 样本 {gap.peer_count} 人</span>'
        f'<div class="vip-gap-track"><i style="width:{gap.gap_ratio * 100:.1f}%"></i></div></div>'
        f'<b>{gap.gap_ratio:.0%}</b></div>'
        for gap in gaps
    )
    st.markdown(
        '<div class="vip-profile-panel"><div class="vip-profile-panel-head">'
        '<div><strong>分项战力缺口</strong><br><span>参照有效 VIP 榜单；优先同养成阶段，中位数比较，样本不足时逐级回退</span></div>'
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
        ("现金购买", coverage.cash_purchases, "role_pay 明细"),
        ("龙币支付", coverage.dragon_coin_purchases, "Item 同秒关联"),
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


def _load_price_tiers(st, db_path, workbook) -> dict[str, float]:
    sheet_names = tuple(getattr(getattr(workbook, "report", None), "sheet_names", ()))
    if db_path is None or not any(str(name).startswith("AE项目") for name in sheet_names):
        return {}
    repository = AEVIPSnapshotRepository(db_path)
    latest_run = repository.get_latest_run(DEFAULT_AE_PROJECT_ID)
    revision = str(latest_run["finished_at"] if latest_run else "")

    @st.cache_data(show_spinner=False, ttl=600)
    def _cached(path: str, source_revision: str) -> dict[str, float]:
        del source_revision
        all_rows = AEVIPSnapshotRepository(path).list_purchase_packages_by_channel(
            DEFAULT_AE_PROJECT_ID,
            "cash",
        )
        frame = pd.DataFrame([dict(row) for row in all_rows]) if all_rows else pd.DataFrame()
        return infer_package_price_tiers(frame)

    return _cached(str(db_path), revision)


def _load_purchase_window_status(db_path, workbook) -> dict[str, str]:
    sheet_names = tuple(getattr(getattr(workbook, "report", None), "sheet_names", ()))
    if db_path is None or not any(str(name).startswith("AE项目") for name in sheet_names):
        return {}
    latest = AEVIPSnapshotRepository(db_path).get_latest_successful_run(
        DEFAULT_AE_PROJECT_ID
    )
    if latest is None:
        return {}
    available_columns = set(latest.keys())
    field_map = {
        "lifetime": "purchase_lifetime_window",
        "recent_7d": "purchase_7d_window",
        "recent_14d": "purchase_14d_window",
        "recent_30d": "purchase_recent_window",
    }
    return {
        window_key: str(latest[field] or "")
        for window_key, field in field_map.items()
        if field in available_columns and latest[field]
    }


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
        '<span>战力参照：有效 VIP 榜单</span>'
        '<span>礼包口径：礼包名定方向；标准档位 × 购买次数，现金与龙币同款合并</span>'
        '<span>退款、撤销及非消费事件不计</span></div>',
        unsafe_allow_html=True,
    )
    player = _render_selector(st, workbook.active_df)
    if player is None:
        return
    role_id = _safe_text(player.get("角色ID"), "")
    purchase_rows = _load_purchase_rows(db_path, workbook, role_id)
    price_tiers = _load_price_tiers(st, db_path, workbook)
    purchase_window_status = _load_purchase_window_status(db_path, workbook)
    insight = build_profile_insight(
        player,
        purchase_rows,
        workbook.active_df,
        as_of=as_of,
        price_tiers=price_tiers,
    )
    _render_hero(st, player, insight, as_of)
    _render_metrics(st, player)
    _render_recommendations(st, insight)
    columns = st.columns([1.05, 0.95], gap="large")
    with columns[0]:
        _render_purchase_panel(st, purchase_rows, price_tiers, purchase_window_status)
    with columns[1]:
        _render_power_gap_panel(st, insight)
    lower_columns = st.columns([1.05, 0.95], gap="large")
    with lower_columns[0]:
        _render_stage_panel(st, player, as_of)
    with lower_columns[1]:
        _render_coverage_panel(st, insight)
