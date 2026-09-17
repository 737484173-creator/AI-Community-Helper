from __future__ import annotations

from html import escape

from app.dashboard.bot_control_service import BotControlService
from app.dashboard.data_service import DashboardDataService, DashboardMetrics
from app.dashboard.styles import icon_svg
from config.settings import get_settings


def _get_today_metrics(st, db_path) -> DashboardMetrics:
    @st.cache_data(ttl=15, show_spinner=False)
    def _cached_today_metrics(path: str) -> DashboardMetrics:
        return DashboardDataService(path).get_today_metrics()

    return _cached_today_metrics(str(db_path))


def _inject_dashboard_styles(st) -> None:
    st.markdown(
        """
        <style>
        div.stVerticalBlock.st-key-dashboard_bot_control {
            gap: 8px;
            margin: 2px 0 18px;
            padding: 12px 0;
            border-top: 1px solid var(--border);
            border-bottom: 1px solid var(--border);
        }
        div.stVerticalBlock.st-key-dashboard_bot_control [data-testid="stHorizontalBlock"] {
            align-items: center;
        }
        div.stVerticalBlock.st-key-dashboard_bot_control button {
            min-height: 38px;
        }
        .dashboard-overview-canvas {
            display: grid;
            grid-template-columns: minmax(280px, .82fr) minmax(0, 1.35fr);
            margin: 0 0 20px;
            overflow: hidden;
            border: 1px solid var(--border);
            border-radius: var(--radius-panel);
            background: var(--surface);
            box-shadow: var(--shadow-1);
            animation: content-enter var(--motion-enter) var(--ease-standard) both;
            transition:
                transform var(--motion-standard) var(--ease-standard),
                border-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        .dashboard-overview-canvas:hover {
            transform: translateY(-2px);
            border-color: color-mix(in srgb, var(--primary) 20%, var(--border));
            box-shadow: var(--shadow-2);
        }
        .dashboard-activity-pane {
            position: relative;
            display: flex;
            min-height: 280px;
            padding: 28px;
            flex-direction: column;
            justify-content: space-between;
            border-right: 1px solid var(--border);
            background: color-mix(in srgb, var(--primary-soft) 28%, var(--surface));
            transition:
                background-color var(--motion-standard) var(--ease-standard),
                box-shadow var(--motion-standard) var(--ease-standard);
        }
        .dashboard-activity-pane:hover {
            background: color-mix(in srgb, var(--primary-soft) 52%, var(--surface));
            box-shadow: inset -1px 0 0 color-mix(in srgb, var(--primary) 12%, transparent);
        }
        .dashboard-activity-pane::after {
            position: absolute;
            right: 0;
            bottom: 0;
            width: 46%;
            height: 2px;
            background: var(--primary);
            content: "";
            opacity: .72;
            transform-origin: right center;
            transition:
                width var(--motion-standard) var(--ease-standard),
                opacity var(--motion-fast) var(--ease-standard);
        }
        .dashboard-activity-pane:hover::after {
            width: 72%;
            opacity: 1;
        }
        .dashboard-section-label {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: var(--text-secondary);
            font-size: 13px;
            font-weight: 680;
        }
        .dashboard-section-label svg {
            width: 17px;
            height: 17px;
            color: var(--primary);
            transition:
                transform var(--motion-standard) var(--ease-standard),
                filter var(--motion-standard) var(--ease-standard);
        }
        .dashboard-activity-pane:hover .dashboard-section-label svg,
        .dashboard-work-pane:hover .dashboard-section-label svg {
            transform: translateY(-1px) scale(1.06);
            filter: drop-shadow(0 3px 5px color-mix(in srgb, var(--primary) 24%, transparent));
        }
        .dashboard-hero-metric {
            display: flex;
            align-items: baseline;
            gap: 10px;
            margin: 20px 0 4px;
        }
        .dashboard-hero-metric strong {
            color: var(--text-primary);
            font-size: clamp(54px, 6vw, 76px);
            font-weight: 735;
            font-variant-numeric: tabular-nums;
            line-height: .95;
            letter-spacing: -.06em;
            transition:
                transform var(--motion-standard) var(--ease-standard),
                color var(--motion-standard) var(--ease-standard);
        }
        .dashboard-activity-pane:hover .dashboard-hero-metric strong {
            transform: translateY(-2px);
            color: var(--primary-hover);
        }
        .dashboard-hero-metric span {
            color: var(--text-secondary);
            font-size: 14px;
            font-weight: 620;
        }
        .dashboard-activity-caption {
            color: var(--text-secondary);
            font-size: 13px;
            line-height: 1.55;
            text-wrap: pretty;
        }
        .dashboard-activity-footer {
            display: grid;
            grid-template-columns: 1fr 1.35fr;
            gap: 16px;
            align-items: end;
            margin-top: 28px;
            padding-top: 16px;
            border-top: 1px solid color-mix(in srgb, var(--border) 82%, transparent);
        }
        .dashboard-secondary-value span,
        .dashboard-activity-state span {
            display: block;
            margin-bottom: 4px;
            color: var(--text-tertiary);
            font-size: 11px;
            font-weight: 640;
        }
        .dashboard-secondary-value strong {
            color: var(--text-primary);
            font-size: 24px;
            font-weight: 720;
            font-variant-numeric: tabular-nums;
        }
        .dashboard-activity-state {
            color: var(--text-secondary);
            font-size: 12px;
            line-height: 1.5;
        }
        .dashboard-work-pane {
            min-width: 0;
            padding: 28px 30px 22px;
            transition: background-color var(--motion-standard) var(--ease-standard);
        }
        .dashboard-work-pane:hover {
            background: color-mix(in srgb, var(--primary-soft) 18%, var(--surface));
        }
        .dashboard-work-head {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 18px;
            padding-bottom: 18px;
        }
        .dashboard-work-title {
            margin-top: 7px;
            color: var(--text-primary);
            font-size: 20px;
            font-weight: 710;
            line-height: 1.25;
            letter-spacing: -.02em;
        }
        .dashboard-attention-count {
            min-width: 78px;
            text-align: right;
        }
        .dashboard-attention-count strong {
            display: block;
            color: var(--text-primary);
            font-size: 30px;
            font-weight: 730;
            font-variant-numeric: tabular-nums;
            line-height: 1;
            transition:
                transform var(--motion-standard) var(--ease-standard),
                color var(--motion-standard) var(--ease-standard);
        }
        .dashboard-work-pane:hover .dashboard-attention-count strong {
            transform: translateY(-2px);
            color: var(--primary-hover);
        }
        .dashboard-attention-count span {
            color: var(--text-tertiary);
            font-size: 11px;
        }
        .dashboard-work-list {
            border-top: 1px solid var(--border);
        }
        .dashboard-work-row {
            display: grid;
            grid-template-columns: 36px minmax(0, 1fr) auto;
            gap: 14px;
            align-items: center;
            min-height: 64px;
            border-bottom: 1px solid var(--border);
            transition:
                transform var(--motion-fast) var(--ease-standard),
                background-color var(--motion-fast) var(--ease-standard),
                box-shadow var(--motion-fast) var(--ease-standard);
        }
        .dashboard-work-row:hover {
            transform: translateX(2px);
            background: color-mix(in srgb, var(--primary-soft) 42%, transparent);
            box-shadow: inset 2px 0 0 color-mix(in srgb, var(--primary) 58%, transparent);
        }
        .dashboard-work-row:last-child {
            border-bottom: 0;
        }
        .dashboard-work-index {
            color: var(--text-tertiary);
            font-size: 11px;
            font-variant-numeric: tabular-nums;
            letter-spacing: .08em;
            transition: color var(--motion-fast) var(--ease-standard);
        }
        .dashboard-work-row:hover .dashboard-work-index {
            color: var(--primary);
        }
        .dashboard-work-copy strong {
            display: block;
            color: var(--text-primary);
            font-size: 14px;
            font-weight: 670;
        }
        .dashboard-work-copy span {
            display: block;
            margin-top: 3px;
            color: var(--text-tertiary);
            font-size: 12px;
            line-height: 1.35;
            text-wrap: pretty;
        }
        .dashboard-work-value {
            min-width: 52px;
            color: var(--text-primary);
            font-size: 22px;
            font-weight: 720;
            font-variant-numeric: tabular-nums;
            text-align: right;
            transition: transform var(--motion-fast) var(--ease-standard);
        }
        .dashboard-work-row:hover .dashboard-work-value {
            transform: translateY(-1px) scale(1.035);
        }
        .dashboard-work-value.warning {
            color: var(--warning);
        }
        .dashboard-work-value.danger {
            color: var(--danger);
        }
        @media (max-width: 820px) {
            .dashboard-overview-canvas {
                grid-template-columns: 1fr;
            }
            .dashboard-activity-pane {
                min-height: 230px;
                border-right: 0;
                border-bottom: 1px solid var(--border);
            }
        }
        @media (max-width: 560px) {
            div.stVerticalBlock.st-key-dashboard_bot_control [data-testid="stHorizontalBlock"] {
                align-items: stretch;
            }
            .dashboard-activity-pane,
            .dashboard-work-pane {
                padding: 20px;
            }
            .dashboard-activity-footer {
                grid-template-columns: 1fr;
                gap: 10px;
            }
            .dashboard-work-head {
                align-items: flex-end;
            }
            .dashboard-work-row {
                grid-template-columns: 28px minmax(0, 1fr) auto;
                gap: 10px;
            }
        }
        @media (prefers-reduced-motion: reduce) {
            .dashboard-overview-canvas,
            .dashboard-activity-pane,
            .dashboard-activity-pane::after,
            .dashboard-section-label svg,
            .dashboard-hero-metric strong,
            .dashboard-work-pane,
            .dashboard-attention-count strong,
            .dashboard-work-row,
            .dashboard-work-index,
            .dashboard-work-value {
                animation: none !important;
                transition: none !important;
            }
            .dashboard-overview-canvas:hover,
            .dashboard-activity-pane:hover .dashboard-hero-metric strong,
            .dashboard-work-pane:hover .dashboard-attention-count strong,
            .dashboard-work-row:hover,
            .dashboard-work-row:hover .dashboard-work-value,
            .dashboard-activity-pane:hover .dashboard-section-label svg,
            .dashboard-work-pane:hover .dashboard-section-label svg {
                transform: none !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_bot_status(st) -> None:
    settings = get_settings()
    service = BotControlService(settings)
    status = service.status()
    with st.container(key="dashboard_bot_control"):
        tone = "success" if status.is_running else "warning"
        status_col, start_col, stop_col = st.columns([5, 1, 1])
        status_col.markdown(
            f"""
            <div class="bot-status-compact">
                <div class="bot-status-title"><span class="status-dot {tone}"></span> DC Bot {status.label}</div>
                <div class="bot-status-detail">{escape(status.detail)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if start_col.button("启动 Bot", disabled=not status.can_start, type="primary", use_container_width=True):
            started = service.start()
            if started.is_running:
                st.success(started.detail)
            else:
                st.error(started.detail)
            st.rerun()
        if stop_col.button("停止 Bot", disabled=not status.can_stop, use_container_width=True):
            stopped = service.stop()
            if stopped.is_running:
                st.warning(stopped.detail)
            else:
                st.success("Discord Bot 已停止")
            st.rerun()


def _render_operations_canvas(st, metrics: DashboardMetrics, bot_running: bool) -> None:
    def display_value(number: int) -> int | str:
        return number if bot_running or number else "—"

    if not bot_running:
        activity_caption = "Bot 当前已停止，新的频道消息暂不会进入工作台。"
    elif metrics.today_messages:
        activity_caption = f"Bot 正在监听社区频道，今天已采集 {metrics.today_messages} 条消息。"
    else:
        activity_caption = "Bot 正在监听社区频道，等待今天的第一条新消息。"

    attention_count = metrics.today_high_risk_messages + metrics.open_pending_tickets
    attention_title = "当前没有优先待办" if attention_count == 0 else "需要及时处理的运营事项"
    activity_state = "在线监听" if bot_running else "采集暂停"
    message_value = display_value(metrics.today_messages)
    reply_value = display_value(metrics.today_ai_replies)
    st.markdown(
        f"""
        <section class="dashboard-overview-canvas" aria-label="今日运营概览">
            <div class="dashboard-activity-pane">
                <div>
                        <div class="dashboard-section-label">{icon_svg('message')} 社区活跃度</div>
                    <div class="dashboard-hero-metric"><strong>{escape(str(message_value))}</strong><span>今日消息</span></div>
                    <div class="dashboard-activity-caption">{escape(activity_caption)}</div>
                </div>
                <div class="dashboard-activity-footer">
                    <div class="dashboard-secondary-value"><span>AI 自动回复</span><strong>{escape(str(reply_value))}</strong></div>
                    <div class="dashboard-activity-state"><span>采集状态</span>{escape(activity_state)}</div>
                </div>
            </div>
            <div class="dashboard-work-pane">
                <div class="dashboard-work-head">
                    <div>
                        <div class="dashboard-section-label">{icon_svg('task')} 当前处理概览</div>
                        <div class="dashboard-work-title">{escape(attention_title)}</div>
                    </div>
                    <div class="dashboard-attention-count"><strong>{attention_count}</strong><span>需关注</span></div>
                </div>
                <div class="dashboard-work-list" role="list">
                    <div class="dashboard-work-row" role="listitem">
                        <span class="dashboard-work-index">01</span>
                        <div class="dashboard-work-copy"><strong>今日新增反馈</strong><span>BUG、建议与负面意见的新增归档</span></div>
                        <strong class="dashboard-work-value">{metrics.today_feedback}</strong>
                    </div>
                    <div class="dashboard-work-row" role="listitem">
                        <span class="dashboard-work-index">02</span>
                        <div class="dashboard-work-copy"><strong>高风险言论处理</strong><span>今日高风险言论需优先巡检</span></div>
                        <strong class="dashboard-work-value danger">{metrics.today_high_risk_messages}</strong>
                    </div>
                    <div class="dashboard-work-row" role="listitem">
                        <span class="dashboard-work-index">03</span>
                        <div class="dashboard-work-copy"><strong>FAQ 待答</strong><span>知识库未命中的人工答复队列</span></div>
                        <strong class="dashboard-work-value warning">{metrics.open_pending_tickets}</strong>
                    </div>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render(st, db_path) -> None:
    _inject_dashboard_styles(st)
    metrics = _get_today_metrics(st, db_path)

    _render_bot_status(st)
    bot_running = BotControlService(get_settings()).status().is_running
    _render_operations_canvas(st, metrics, bot_running)
