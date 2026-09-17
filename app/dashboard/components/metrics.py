from __future__ import annotations

from app.dashboard.styles import dashboard_card


def render_metric_row(st, metrics) -> None:
    cards = "".join(
        [
            dashboard_card("今日消息", metrics.today_messages, "message", "当天 Discord 消息量"),
            dashboard_card("AI 回复", metrics.today_ai_replies, "sparkles", "自动回复数量"),
            dashboard_card("反馈数量", metrics.today_feedback, "filter", "玩家反馈归档"),
            dashboard_card("高风险言论", metrics.today_high_risk_messages, "alert", "今日需优先巡检"),
            dashboard_card("FAQ 待答", metrics.open_pending_tickets, "help", "知识库未命中的人工答复队列"),
        ]
    )
    st.markdown(
        f'<div class="aidc-metric-grid">{cards}</div>',
        unsafe_allow_html=True,
    )
