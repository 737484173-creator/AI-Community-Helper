from __future__ import annotations

from html import escape

import pandas as pd

from app.database.repositories.member_review_repository import MemberReviewRepository
from app.member_review.config_loader import (
    current_server_date,
    load_planned_server_dates,
    load_review_rules,
    load_server_mapping,
)
from app.member_review.messages import generate_rejection_reason
from app.member_review.models import REVIEW_STATUSES
from app.member_review.parser import parse_member_application
from app.member_review.recheck import (
    PRIORITY_CATEGORIES,
    RECHECK_CATEGORIES,
    RECHECK_DATE,
    load_recheck_snapshot,
    recheck_snapshot_path,
)
from app.member_review.service import MemberReviewService


STATUS_TONES = {
    "可通过": "success",
    "信息不完整": "warning",
    "区服ID异常": "warning",
    "需要人工审核": "info",
    "已通过": "success",
    "已拒绝": "neutral",
}


def _status_pill(label: str, tone: str = "neutral") -> str:
    return f'<span class="status-pill {escape(tone)}">{escape(label)}</span>'


def _member_review_css(st) -> None:
    st.markdown(
        """
        <style>
        .member-format-card {
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:16px;
            padding:18px 20px;
            border:1px solid #E6EAF0;
            border-radius:16px;
            background:#FFFFFF;
            margin-bottom:16px;
        }
        .member-format-title {
            font-size:16px;
            font-weight:650;
            color:#1D1D1F;
            margin-bottom:4px;
        }
        .member-format-copy {
            color:#6E6E73;
            font-size:13px;
            line-height:20px;
        }
        .member-format-example {
            padding:10px 14px;
            border-radius:999px;
            background:#EEF5FF;
            color:#2563EB;
            font-weight:650;
            white-space:nowrap;
        }
        .member-sync-card {
            display:grid;
            grid-template-columns:1fr auto;
            gap:16px;
            align-items:center;
            padding:14px 16px;
            border:1px solid #D7E6FF;
            border-radius:14px;
            background:#F5F9FF;
            margin:12px 0 16px;
        }
        .member-sync-title {
            color:#1D1D1F;
            font-size:14px;
            font-weight:650;
            margin-bottom:4px;
        }
        .member-sync-copy {
            color:#5F6F86;
            font-size:13px;
            line-height:20px;
        }
        .member-sync-badge {
            border-radius:999px;
            padding:6px 10px;
            background:#FFFFFF;
            border:1px solid #CFE0F8;
            color:#2563EB;
            font-size:12px;
            font-weight:650;
            white-space:nowrap;
        }
        .member-metrics {
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:14px;
            margin:12px 0 18px;
        }
        .member-metric-card {
            min-height:82px;
            padding:16px;
            border:1px solid #E6EAF0;
            border-radius:16px;
            background:#fff;
        }
        .member-metric-label {
            color:#6E6E73;
            font-size:12px;
            margin-bottom:6px;
        }
        .member-metric-value {
            color:#1D1D1F;
            font-size:28px;
            line-height:32px;
            font-weight:700;
        }
        .member-filter-card,
        .member-detail-card {
            padding:16px;
            border:1px solid #E6EAF0;
            border-radius:16px;
            background:#F8FAFC;
            margin:10px 0 16px;
        }
        .member-section-title {
            font-size:20px;
            font-weight:650;
            color:#1D1D1F;
            margin:18px 0 4px;
        }
        .member-section-caption {
            color:#6E6E73;
            font-size:13px;
            margin-bottom:10px;
        }
        .member-detail-grid {
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:12px;
        }
        .member-detail-cell {
            border:1px solid #E6EAF0;
            border-radius:12px;
            background:#fff;
            padding:12px;
            min-height:72px;
        }
        .member-detail-cell span {
            display:block;
            color:#8A94A3;
            font-size:12px;
            margin-bottom:6px;
        }
        .member-detail-cell strong {
            color:#1D1D1F;
            font-size:14px;
            overflow-wrap:anywhere;
        }
        .member-raw-box {
            border:1px solid #E6EAF0;
            border-radius:12px;
            background:#fff;
            padding:14px;
            color:#1D1D1F;
            line-height:22px;
            white-space:pre-wrap;
            margin-top:12px;
        }
        .member-recheck-note {
            margin:10px 0 14px;
            padding:11px 14px;
            border-left:3px solid var(--primary);
            border-radius:0 var(--radius-card) var(--radius-card) 0;
            background:color-mix(in srgb,var(--primary-soft) 34%,var(--surface));
            color:var(--text-secondary);
            font-size:13px;
            line-height:21px;
        }
        .member-recheck-note strong { color:var(--text-primary); }
        .member-format-card {
            padding:16px 2px;
            margin-bottom:18px;
            border:0;
            border-top:1px solid var(--border-strong);
            border-bottom:1px solid var(--border);
            border-radius:0;
            background:transparent;
            animation:content-enter var(--motion-enter) var(--ease-standard) both;
        }
        .member-metric-card,
        .member-detail-cell,
        .member-raw-box { background:var(--surface); border-color:var(--border); border-radius:var(--radius-card); }
        .member-format-title,
        .member-metric-value,
        .member-section-title,
        .member-detail-cell strong,
        .member-raw-box { color:var(--text-primary); }
        .member-format-copy,
        .member-metric-label,
        .member-section-caption { color:var(--text-secondary); }
        .member-detail-cell span { color:var(--text-tertiary); }
        .member-format-example { background:var(--primary-soft); color:var(--primary); }
        .member-sync-card {
            padding:14px 2px;
            margin:10px 0 0;
            border:0;
            border-top:1px solid var(--border);
            border-bottom:1px solid var(--border);
            border-radius:0;
            background:transparent;
        }
        .member-sync-title { color:var(--text-primary); }
        .member-sync-copy { color:var(--text-secondary); }
        .member-sync-badge { background:var(--primary-soft); border-color:color-mix(in srgb,var(--primary) 20%,var(--border)); color:var(--primary); }
        .member-metrics {
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:0;
            margin:0 0 22px;
            overflow:hidden;
            border-bottom:1px solid var(--border-strong);
            background:color-mix(in srgb,var(--surface) 54%,transparent);
            animation:content-enter var(--motion-enter) var(--ease-standard) 40ms both;
            transform:translateY(0);
            transition:
                transform var(--motion-standard) var(--ease-standard),
                border-color var(--motion-standard) var(--ease-standard),
                background-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        .member-metrics:hover {
            transform:translateY(-2px);
            border-color:color-mix(in srgb,var(--primary) 22%,var(--border));
            background:color-mix(in srgb,var(--primary-soft) 14%,var(--surface));
            box-shadow:var(--shadow-2);
        }
        .member-metric-card {
            position:relative;
            min-width:0;
            min-height:102px;
            padding:17px 18px 16px;
            border:0;
            border-radius:0;
            background:transparent;
            transition:
                background-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        .member-metric-card+.member-metric-card{border-left:1px solid var(--border);}
        .member-metric-card:first-child{background:color-mix(in srgb,var(--primary-soft) 22%,transparent);}
        .member-metric-card:hover{
            background:color-mix(in srgb,var(--primary-soft) 42%,var(--surface));
            box-shadow:inset 0 -2px 0 color-mix(in srgb,var(--primary) 58%,transparent);
        }
        .member-metric-value{
            display:inline-block;
            font-size:31px;
            line-height:34px;
            font-variant-numeric:tabular-nums;
            letter-spacing:-.04em;
            transform-origin:left center;
            transition:
                transform var(--motion-standard) var(--ease-standard),
                color var(--motion-standard) var(--ease-standard);
        }
        .member-metric-card:hover .member-metric-value{
            color:var(--primary-hover);
            transform:translateY(-1px) scale(1.025);
        }
        .member-filter-card,.member-detail-card {
            padding:16px 0;
            border:0;
            border-top:1px solid var(--border-strong);
            border-radius:0;
            background:transparent;
        }
        @media (max-width: 980px) {
            .member-metrics, .member-detail-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .member-format-card { flex-direction:column; align-items:flex-start; }
            .member-metric-card:nth-child(3){border-left:0;border-top:1px solid var(--border);}
            .member-metric-card:nth-child(4){border-top:1px solid var(--border);}
        }
        @media (max-width:560px) {
            .member-metrics,.member-detail-grid{grid-template-columns:1fr 1fr;gap:8px;}
            .member-metrics{gap:0;}
            .member-metric-card{min-height:88px;padding:12px;}
            .member-sync-card{grid-template-columns:1fr;}
        }
        @media (prefers-reduced-motion: reduce) {
            .member-format-card,
            .member-metrics,
            .member-metric-card,
            .member-metric-value{
                animation:none!important;
                transition:none!important;
            }
            .member-metrics:hover,
            .member-metric-card:hover .member-metric-value{transform:none!important;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_sync_notice(st, local_pending_count: int) -> None:
    cols = st.columns([1, 0.22])
    cols[0].markdown(
        f"""
        <div class="member-sync-card">
            <div>
                <div class="member-sync-title">Discord 待定申请同步状态</div>
                <div class="member-sync-copy">
                    下方数字统计的是已同步到本地工作台的审核队列，不等同于 Discord 后台“待定”页的实时总数。
                    Bot 启动后会同步 Discord Join Requests；如果权限失效，会退回到可见 pending 成员同步。
                </div>
            </div>
            <div class="member-sync-badge">本地待审核 {int(local_pending_count)} 条</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if cols[1].button("同步 Discord 申请", use_container_width=True):
        try:
            synced = MemberReviewService().sync_discord_join_requests()
        except RuntimeError as exc:
            st.error(str(exc))
        else:
            st.success(f"已同步 {synced} 条 Discord 待定申请。")
            st.rerun()


def _latest_server_id(server_mapping: dict[str, str]) -> int:
    return max((int(server_id) for server_id in server_mapping if server_id.isdecimal()), default=50)


def _render_format_card(st, server_mapping: dict[str, str]) -> None:
    latest_server = _latest_server_id(server_mapping)
    st.markdown(
        f"""
        <div class="member-format-card">
            <div>
                <div class="member-format-title">推荐填写格式</div>
                <div class="member-format-copy">
                    当前支持 S1–S{latest_server}。例如 S{latest_server} Bubble 或 {latest_server} Bubble。区服 ID 和角色名称前后顺序均可，系统会自动识别。
                    已合服玩家也可填写原区服，例如 S12 Bubble 会按主服 S11 审核并命名。
                    英文提示：Please provide your server ID and in-game character name. For example: S{latest_server} Bubble or {latest_server} Bubble.
                </div>
            </div>
            <div class="member-format-example">S{latest_server} Bubble</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_metrics(st, counts: dict[str, int]) -> None:
    items = [
        ("待审核", counts.get("待审核", 0), "所有未处理申请"),
        ("可通过", counts.get("可通过", 0), "识别完整且无冲突"),
        ("信息不完整", counts.get("信息不完整", 0), "缺角色名或区服ID"),
        ("需要人工审核", counts.get("需要人工审核", 0) + counts.get("区服ID异常", 0), "异常、冲突或非法区服"),
    ]
    html = "<div class='member-metrics'>"
    for label, value, helper in items:
        html += (
            "<div class='member-metric-card'>"
            f"<div class='member-metric-label'>{escape(label)}</div>"
            f"<div class='member-metric-value'>{value}</div>"
            f"<div class='member-metric-label'>{escape(helper)}</div>"
            "</div>"
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _format_rows(rows) -> list[dict]:
    data = []
    for row in rows:
        data.append(
            {
                "ID": row["id"],
                "Discord用户": row["discord_username"],
                "Discord ID": row["discord_user_id"],
                "原始申请内容": row["raw_application"],
                "角色名": row["player_name"] or "",
                "原始区服输入": row["raw_server_input"] or "",
                "标准化区服": row["server_name"] or "",
                "自动昵称": row["discord_nickname"] or "",
                "提交时间": row["created_time"],
                "审核状态": row["review_status"],
                "审核原因": row["internal_reason"],
                "已处理": "是" if row["processed"] else "否",
            }
        )
    return data


def _format_application_option(row) -> str:
    status = str(row["review_status"])
    raw_application = str(row["raw_application"] or "").replace("\n", " ").strip()
    raw_preview = raw_application[:36] + ("..." if len(raw_application) > 36 else "")
    server = row["server_name"] or row["raw_server_input"] or "未识别区服"
    return f"#{int(row['id'])} · {status} · {server} · {raw_preview}"


def _filters(st, server_mapping: dict[str, str]) -> tuple[str, str, str, str]:
    with st.container(border=True):
        cols = st.columns(4)
        status = cols[0].selectbox("审核状态", ("All", *REVIEW_STATUSES), format_func=lambda value: "全部" if value == "All" else value)
        server_options = ("All", *server_mapping.keys())
        server_id = cols[1].selectbox("区服", server_options, format_func=lambda value: "全部" if value == "All" else server_mapping.get(value, f"S{value}"))
        processed = cols[2].selectbox("是否已处理", ("All", "未处理", "已处理"), format_func=lambda value: "全部" if value == "All" else value)
        auto_filter = cols[3].selectbox("是否可自动通过", ("All", "可自动通过", "不可自动通过"), format_func=lambda value: "全部" if value == "All" else value)
    return status, server_id, processed, auto_filter


def _render_detail(st, db_path, application_id: int) -> None:
    repository = MemberReviewRepository(db_path)
    row = repository.get(application_id)
    if row is None:
        st.warning("未找到该申请。")
        return
    rejection_default = row["rejection_reason"] or generate_rejection_reason(row["reason_code"])
    st.markdown(
        "<div class='member-detail-card'>"
        f"<div class='member-section-title'>申请详情 #{int(row['id'])}</div>"
        f"<div>{_status_pill(str(row['review_status']), STATUS_TONES.get(str(row['review_status']), 'neutral'))}</div>"
        "<div class='member-detail-grid'>"
        f"<div class='member-detail-cell'><span>Discord 用户</span><strong>{escape(str(row['discord_username']))}</strong></div>"
        f"<div class='member-detail-cell'><span>Discord ID</span><strong>{escape(str(row['discord_user_id']))}</strong></div>"
        f"<div class='member-detail-cell'><span>提交时间</span><strong>{escape(str(row['created_time']))}</strong></div>"
        f"<div class='member-detail-cell'><span>置信度</span><strong>{float(row['confidence'] or 0):.0%}</strong></div>"
        f"<div class='member-detail-cell'><span>角色名称</span><strong>{escape(str(row['player_name'] or '未识别'))}</strong></div>"
        f"<div class='member-detail-cell'><span>区服ID</span><strong>{escape(str(row['server_id'] or '未识别'))}</strong></div>"
        f"<div class='member-detail-cell'><span>标准化区服</span><strong>{escape(str(row['server_name'] or '未识别'))}</strong></div>"
        f"<div class='member-detail-cell'><span>最终昵称</span><strong>{escape(str(row['discord_nickname'] or '暂无'))}</strong></div>"
        "</div>"
        f"<div class='member-raw-box'><strong>原始申请</strong><br>{escape(str(row['raw_application']))}</div>"
        f"<div class='member-raw-box'><strong>审核判断</strong><br>{escape(str(row['internal_reason']))}</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.text_area("玩家将收到的英文拒绝理由", value=rejection_default, key=f"member_rejection_{application_id}", height=120)
    action_cols = st.columns(4)
    if action_cols[0].button("确认通过", disabled=str(row["review_status"]) not in {"可通过", "需要人工审核"}, type="primary", use_container_width=True):
        try:
            result = MemberReviewService(db_path).approve(application_id, reviewer="Dashboard")
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success(result.detail)
            if row["discord_nickname"]:
                st.info(f"需要手动设置昵称时可复制：{row['discord_nickname']}")
            st.rerun()
    if action_cols[1].button("确认拒绝", disabled=bool(row["processed"]), use_container_width=True):
        reason = st.session_state.get(f"member_rejection_{application_id}", rejection_default)
        result = MemberReviewService(db_path).reject(application_id, rejection_reason=reason, reviewer="Dashboard")
        st.warning(result.detail)
        st.rerun()
    action_cols[2].button("编辑识别结果", disabled=True, help="预留入口：后续可在人工审核中修改角色名和区服。", use_container_width=True)
    if action_cols[3].button("暂缓", use_container_width=True):
        st.info("已暂缓，本次未执行审核动作。")


def _render_rejected_detail(st, repository: MemberReviewRepository, row, review: dict[str, str] | None) -> None:
    discord_user_id = str(row["discord_user_id"])
    latest_lookup = getattr(repository, "get_latest_by_discord_user_id", None)
    if callable(latest_lookup):
        latest = latest_lookup(discord_user_id)
    else:
        # Streamlit may keep an older imported Repository class until its
        # process restarts, even after this view has hot-reloaded.
        latest = repository._fetch_one(
            """
            SELECT * FROM member_applications
            WHERE discord_user_id = ?
            ORDER BY created_time DESC, id DESC
            LIMIT 1
            """,
            (discord_user_id,),
        )
    if latest is None or int(latest["id"]) == int(row["id"]):
        latest_note = "尚无后续申请；等待玩家重新提交。"
    elif str(latest["final_result"] or "") == "通过":
        latest_note = f"后续申请 #{int(latest['id'])} 已通过；旧拒绝记录仅供追溯。"
    elif not latest["processed"]:
        latest_note = f"后续申请 #{int(latest['id'])} 正在待处理队列；请按新申请审核。"
    else:
        latest_note = f"后续申请 #{int(latest['id'])} 的当前结果：{latest['final_result'] or latest['review_status']}。"
    category = review["复核分类"] if review else "未专项复核"
    evidence = review.get("Discord原表单核验", "未专项核验") if review else "未专项核验"
    current_rule = review.get("现行规则状态", "未专项复核") if review else "未专项复核"
    st.markdown(
        "<div class='member-detail-card'>"
        f"<div class='member-section-title'>已拒绝申请 #{int(row['id'])}</div>"
        f"<div>{_status_pill(category, 'warning' if category in PRIORITY_CATEGORIES else 'neutral')}</div>"
        "<div class='member-detail-grid'>"
        f"<div class='member-detail-cell'><span>Discord 用户</span><strong>{escape(str(row['discord_username']))}</strong></div>"
        f"<div class='member-detail-cell'><span>Discord ID</span><strong>{escape(str(row['discord_user_id']))}</strong></div>"
        f"<div class='member-detail-cell'><span>提交时间（UTC）</span><strong>{escape(str(row['created_time']))}</strong></div>"
        f"<div class='member-detail-cell'><span>原识别区服</span><strong>{escape(str(row['server_name'] or row['raw_server_input'] or '未识别'))}</strong></div>"
        f"<div class='member-detail-cell'><span>原拒绝原因</span><strong>{escape(str(row['reason_code'] or '未记录'))}</strong></div>"
        f"<div class='member-detail-cell'><span>现行规则复核</span><strong>{escape(str(current_rule))}</strong></div>"
        f"<div class='member-detail-cell'><span>Discord 原表单</span><strong>{escape(str(evidence))}</strong></div>"
        f"<div class='member-detail-cell'><span>最近申请</span><strong>{escape(latest_note)}</strong></div>"
        "</div>"
        f"<div class='member-raw-box'><strong>原始申请内容</strong><br>{escape(str(row['raw_application'] or ''))}</div>"
        f"<div class='member-raw-box'><strong>当时的拒绝理由</strong><br>{escape(str(row['rejection_reason'] or row['internal_reason'] or '未记录'))}</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption("历史记录只读，不会重新批准或通知玩家。玩家重新提交后，新的申请会按当前区服开放条件进入原有审核流程。")


def _render_rejected_history(st, db_path, repository: MemberReviewRepository) -> None:
    path = recheck_snapshot_path(db_path)
    try:
        snapshot = load_recheck_snapshot(path)
    except FileNotFoundError:
        snapshot = {}
        st.warning("未找到 2026/09/20 的复核快照；下方仍可查看已拒绝名单，但不会推断复核结论。")
    except (OSError, ValueError) as exc:
        st.error(f"历史拒绝复核数据加载失败：{exc}")
        return

    rows = repository.list_filtered(review_status="已拒绝", processed_filter="已处理", limit=5000)
    if not rows:
        st.markdown('<div class="empty-state">当前没有已拒绝的成员申请。</div>', unsafe_allow_html=True)
        return
    rows_by_id = {int(row["id"]): row for row in rows}

    def review_for(row):
        review = snapshot.get(int(row["id"]))
        return review if review and review["Discord用户ID"] == str(row["discord_user_id"]) else None

    audited = [row for row in rows if review_for(row)]
    priority = [row for row in audited if review_for(row)["复核分类"] in PRIORITY_CATEGORIES]
    priority_users = {str(row["discord_user_id"]) for row in priority}
    st.markdown(
        "<div class='member-recheck-note'>"
        f"<strong>历史拒绝复核 · {RECHECK_DATE}</strong>　已复核 {len(audited)} 条；"
        f"重点关注 {len(priority)} 条 / {len(priority_users)} 位玩家。"
        "旧申请不直接撤销或重新批准，等待玩家重新提交。"
        "</div>",
        unsafe_allow_html=True,
    )
    filter_cols = st.columns([1, 1.6])
    category_options = (
        ("重点关注", "全部已拒绝", *RECHECK_CATEGORIES, "未专项复核")
        if snapshot else ("全部已拒绝", "未专项复核")
    )
    if st.session_state.get("member_recheck_category") not in category_options:
        st.session_state["member_recheck_category"] = category_options[0]
    category = filter_cols[0].selectbox("复核分类", category_options, key="member_recheck_category")
    search = filter_cols[1].text_input("搜索 Discord 用户、角色名或申请内容", key="member_recheck_search").strip().casefold()

    def matches(row) -> bool:
        review = review_for(row)
        group = review["复核分类"] if review else "未专项复核"
        if category == "重点关注" and group not in PRIORITY_CATEGORIES:
            return False
        if category not in {"重点关注", "全部已拒绝"} and group != category:
            return False
        if search and not any(
            search in str(row[field] or "").casefold()
            for field in ("discord_username", "discord_user_id", "player_name", "raw_application")
        ):
            return False
        return True

    visible = [row for row in rows if matches(row)]
    if not visible:
        st.markdown('<div class="empty-state">没有匹配的已拒绝申请，请调整筛选条件。</div>', unsafe_allow_html=True)
        return
    table = [
        {
            "申请ID": int(row["id"]),
            "提交时间（UTC）": str(row["created_time"]),
            "Discord用户": str(row["discord_username"]),
            "原识别区服": str(row["server_name"] or row["raw_server_input"] or "未识别"),
            "原拒绝原因": str(row["reason_code"] or "未记录"),
            "复核分类": review_for(row)["复核分类"] if review_for(row) else "未专项复核",
        }
        for row in visible
    ]
    st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True, height=310)
    visible_by_id = {int(row["id"]): row for row in visible}
    if st.session_state.get("member_recheck_selected_id") not in visible_by_id:
        st.session_state["member_recheck_selected_id"] = next(iter(visible_by_id))
    selected_id = st.selectbox(
        "查看已拒绝申请详情",
        tuple(visible_by_id),
        format_func=lambda value: _format_application_option(visible_by_id[value]),
        key="member_recheck_selected_id",
    )
    selected = rows_by_id[int(selected_id)]
    _render_rejected_detail(st, repository, selected, review_for(selected))


def _render_parser_preview(
    st,
    server_mapping: dict[str, str],
    planned_server_dates: dict[str, str],
) -> None:
    latest_server = _latest_server_id(server_mapping)
    with st.expander("审核规则测试", expanded=False):
        sample = st.text_input("输入申请内容测试解析", value=f"S{latest_server} Bubble King")
        parsed = parse_member_application(
            sample,
            server_mapping,
            planned_server_dates=planned_server_dates,
        )
        st.json(
            {
                "player_name": parsed.player_name,
                "server_id": parsed.server_id,
                "server_name": parsed.server_name,
                "nickname": parsed.discord_nickname,
                "status": parsed.status,
                "reason_code": parsed.reason_code,
                "internal_reason": parsed.internal_reason,
                "rejection_reason": None if parsed.status == "可通过" else generate_rejection_reason(parsed.reason_code),
            }
        )


def render(st, db_path) -> None:
    _member_review_css(st)
    repository = MemberReviewRepository(db_path)
    rules = load_review_rules()
    reference = current_server_date()
    server_mapping = load_server_mapping(as_of=reference)
    planned_server_dates = load_planned_server_dates(as_of=reference)
    _render_format_card(st, server_mapping)
    if planned_server_dates:
        schedule = "、".join(
            f"S{server_id}（{planned_server_dates[server_id]}）"
            for server_id in sorted(planned_server_dates, key=int)
        )
        st.caption(f"已排期开服：{schedule}。到期开服后自动纳入审核；提前申请进入人工复核。")
    mode_label = "人工确认模式" if not rules.get("auto_approve_enabled") else "自动审核模式"
    if rules.get("auto_approve_enabled"):
        mode_detail = "BOT 启动同步时，符合规则的申请会自动通过并修改服务器昵称。"
    else:
        mode_detail = "符合规则的申请会进入队列，等待人工确认。"
    st.caption(f"当前审核模式：{mode_label}。{mode_detail}")
    counts = repository.counts()
    _render_sync_notice(st, counts.get("待审核", 0))
    _render_metrics(st, counts)
    _render_parser_preview(st, server_mapping, planned_server_dates)

    st.markdown("<div class='member-section-title'>申请详情</div>", unsafe_allow_html=True)
    st.session_state.setdefault("member_review_scope", "待处理申请")
    scope = st.segmented_control(
        "申请范围",
        options=("待处理申请", "已拒绝名单（复核）"),
        key="member_review_scope",
        label_visibility="collapsed",
    ) or "待处理申请"
    if scope == "已拒绝名单（复核）":
        _render_rejected_history(st, db_path, repository)
        return
    st.caption("审核队列已隐藏；通过下方选择器切换待处理申请。")
    rows = repository.list_filtered(processed_filter="未处理", limit=500)
    if not rows:
        st.markdown('<div class="empty-state">当前暂无待处理成员申请。</div>', unsafe_allow_html=True)
        return
    selected_id = st.selectbox(
        "查看申请详情",
        [int(row["id"]) for row in rows],
        format_func=lambda value: _format_application_option(
            next(row for row in rows if int(row["id"]) == int(value))
        ),
    )
    _render_detail(st, db_path, int(selected_id))

    logs = repository.list_logs(30)
    if logs:
        with st.expander("审核日志", expanded=False):
            st.dataframe(pd.DataFrame([dict(row) for row in logs]), hide_index=True, use_container_width=True, height=260)
