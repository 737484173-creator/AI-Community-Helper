from __future__ import annotations

from html import escape

import pandas as pd

from app.database.repositories.member_review_repository import MemberReviewRepository
from app.member_review.config_loader import load_review_rules, load_server_mapping
from app.member_review.messages import generate_rejection_reason
from app.member_review.models import REVIEW_STATUSES
from app.member_review.parser import parse_member_application
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


def _render_format_card(st) -> None:
    st.markdown(
        """
        <div class="member-format-card">
            <div>
                <div class="member-format-title">推荐填写格式</div>
                <div class="member-format-copy">
                    S14 Bubble 或 14 Bubble。区服 ID 和角色名称前后顺序均可，系统会自动识别。
                    英文提示：Please provide your server ID and in-game character name. For example: S14 Bubble or 14 Bubble.
                </div>
            </div>
            <div class="member-format-example">S14 Bubble</div>
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


def _render_parser_preview(st) -> None:
    server_mapping = load_server_mapping()
    with st.expander("审核规则测试", expanded=False):
        sample = st.text_input("输入申请内容测试解析", value="S14 Bubble King")
        parsed = parse_member_application(sample, server_mapping)
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
    _render_format_card(st)
    mode_label = "人工确认模式" if not rules.get("auto_approve_enabled") else "自动审核模式"
    if rules.get("auto_approve_enabled"):
        mode_detail = "BOT 启动同步时，符合规则的申请会自动通过并修改服务器昵称。"
    else:
        mode_detail = "符合规则的申请会进入队列，等待人工确认。"
    st.caption(f"当前审核模式：{mode_label}。{mode_detail}")
    counts = repository.counts()
    _render_sync_notice(st, counts.get("待审核", 0))
    _render_metrics(st, counts)
    _render_parser_preview(st)

    st.markdown(
        "<div class='member-section-title'>申请详情</div>"
        "<div class='member-section-caption'>审核队列已隐藏；通过下方选择器切换待处理申请。</div>",
        unsafe_allow_html=True,
    )
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
