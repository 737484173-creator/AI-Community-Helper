from __future__ import annotations

from app.dashboard.data_service import DashboardMetrics
from app.dashboard.views.dashboard import _inject_dashboard_styles, _render_operations_canvas


class MarkdownCapture:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def markdown(self, body: str, **_kwargs) -> None:
        self.calls.append(body)


def test_operations_canvas_replaces_repeated_metric_cards() -> None:
    st = MarkdownCapture()
    metrics = DashboardMetrics(
        today_messages=128,
        today_ai_replies=34,
        today_feedback=9,
        today_high_risk_messages=2,
        open_pending_tickets=3,
    )

    _render_operations_canvas(st, metrics, bot_running=True)

    markup = st.calls[0]
    assert "dashboard-overview-canvas" in markup
    assert "今日消息" in markup and ">128<" in markup
    assert "AI 自动回复" in markup and ">34<" in markup
    assert "今日新增反馈" in markup and ">9<" in markup
    assert "社区活跃度" in markup
    assert "高风险言论处理" in markup and ">2<" in markup
    assert "<strong>5</strong><span>需关注</span>" in markup
    assert "dashboard-card" not in markup


def test_operations_canvas_explains_paused_collection() -> None:
    st = MarkdownCapture()
    metrics = DashboardMetrics(0, 0, 0, 0, 0)

    _render_operations_canvas(st, metrics, bot_running=False)

    markup = st.calls[0]
    assert "Bot 当前已停止" in markup
    assert "采集暂停" in markup
    assert markup.count("<strong>—</strong>") == 2
    assert "当前没有优先待办" in markup


def test_operations_canvas_styles_include_hover_feedback_and_reduced_motion() -> None:
    st = MarkdownCapture()

    _inject_dashboard_styles(st)

    styles = st.calls[0]
    assert ".dashboard-overview-canvas:hover" in styles
    assert ".dashboard-work-row:hover" in styles
    assert "prefers-reduced-motion: reduce" in styles
