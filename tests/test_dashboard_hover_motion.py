from __future__ import annotations

from app.dashboard.views.feedback_center import _feedback_css
from app.dashboard.views.member_review import _member_review_css
from app.dashboard.views.vip_operations import _vip_overview_css
from app.dashboard.views.vip_red_black import _render_chart_motion_css


class MarkdownCapture:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def markdown(self, body: str, **_kwargs) -> None:
        self.calls.append(body)


def test_vip_overview_styles_include_metric_and_file_hover_feedback() -> None:
    st = MarkdownCapture()

    _vip_overview_css(st)

    styles = st.calls[0]
    assert ".vip-metric-band:hover" in styles
    assert ".vip-metric-item:hover .vip-metric-value" in styles
    assert ".vip-file-status-card:hover" in styles
    assert ".vip-ranking-panel:hover" in styles
    assert ".vip-ranking-row:hover" in styles
    assert ".vip-ranking-entry[open] .vip-player-hint" in styles
    assert ".vip-ranking-list::-webkit-scrollbar" in styles
    assert "scrollbar-width: none" in styles
    assert ".vip-server-row:hover" in styles
    assert "@keyframes vip-ranking-bar-grow" in styles
    assert "@keyframes vip-player-detail-reveal" in styles
    assert "st-key-vip_contact_insight_drawer" in styles
    assert "prefers-reduced-motion: reduce" in styles


def test_feedback_overview_styles_include_hover_feedback_and_reduced_motion() -> None:
    st = MarkdownCapture()

    _feedback_css(st)

    styles = st.calls[0]
    assert ".feedback-overview:hover" in styles
    assert ".feedback-card:hover .feedback-card-value" in styles
    assert "prefers-reduced-motion:reduce" in styles


def test_member_review_metrics_include_hover_feedback_and_reduced_motion() -> None:
    st = MarkdownCapture()

    _member_review_css(st)

    styles = st.calls[0]
    assert ".member-metrics:hover" in styles
    assert ".member-metric-card:hover .member-metric-value" in styles
    assert "prefers-reduced-motion: reduce" in styles


def test_red_black_overview_uses_metric_band_hover_feedback() -> None:
    st = MarkdownCapture()

    _render_chart_motion_css(st)

    styles = st.calls[0]
    assert ".red-black-metric-band:hover" in styles
    assert ".red-black-metric-item:hover .red-black-metric-value" in styles
    assert ".red-black-metric-item.tone-red" in styles
    assert ".red-black-metric-item.tone-black" in styles
    assert '.st-key-vip_red_black_tabs [role="tab"]:focus:not(:focus-visible)' in styles
    assert '.st-key-vip_red_black_tabs [role="tab"]:focus-visible' in styles
    assert "prefers-reduced-motion: reduce" in styles
