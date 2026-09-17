from __future__ import annotations

import pandas as pd

from app.dashboard.views.vip_operations import (
    _contact_ranking_frame,
    _render_contact_ranking,
    _render_server_contact_chart,
    _server_contact_frame,
)


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeStreamlit:
    def __init__(self) -> None:
        self.markdowns: list[str] = []

    def container(self, **_kwargs):
        return _Context()

    def markdown(self, body: str, **_kwargs) -> None:
        self.markdowns.append(body)

    def info(self, *_args, **_kwargs) -> None:
        return None

def _insight_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "角色名": "Alpha",
                "角色ID": "1",
                "区服": "1",
                "玩家分组": "老服自然量",
                "触达优先级": "立即触达",
                "价值分": 40,
                "风险分": 30,
                "累计充值": 20000,
                "近一周充值": 0,
                "最后登录时间": "2026-09-01",
                "原因": "高价值、近期未充值",
            },
            {
                "角色名": "Beta",
                "角色ID": "2",
                "区服": "1",
                "玩家分组": "老服自然量",
                "触达优先级": "优先触达",
                "价值分": 35,
                "风险分": 20,
                "累计充值": 5000,
                "近一周充值": 10,
                "最后登录时间": "2026-09-08",
                "原因": "高价值、充值下降",
            },
            {
                "角色名": "Gamma",
                "角色ID": "3",
                "区服": "22",
                "玩家分组": "新服CPS",
                "触达优先级": "暂不触达",
                "价值分": 12,
                "风险分": 10,
                "累计充值": 1200,
                "近一周充值": 100,
                "最后登录时间": "2026-09-09",
                "原因": "消费与活跃相对稳定",
            },
        ]
    )


def test_contact_ranking_combines_value_and_risk_and_excludes_non_contact_players() -> None:
    ranking = _contact_ranking_frame(_insight_rows())

    assert ranking["角色名"].tolist() == ["Alpha", "Beta"]
    assert ranking["综合风险系数"].tolist() == [70, 55]
    assert ranking["排名"].tolist() == [1, 2]
    assert ranking["排行标签"].tolist() == ["01  Alpha · S1", "02  Beta · S1"]


def test_server_contact_frame_uses_current_server_labels_and_contact_priorities() -> None:
    servers = _server_contact_frame(_insight_rows())

    assert servers[["区服标签", "待触达人数"]].to_dict("records") == [
        {"区服标签": "S1", "待触达人数": 2}
    ]


def test_contact_ranking_panel_is_descending_and_exposes_score_components() -> None:
    fake_st = _FakeStreamlit()

    _render_contact_ranking(fake_st, _insight_rows())

    rendered = "".join(fake_st.markdowns)
    assert "vip-ranking-panel" in rendered
    assert rendered.index("Alpha") < rendered.index("Beta")
    assert "立即触达" in rendered
    assert "优先触达" in rendered
    assert "vip-ranking-entry" in rendered
    assert "vip-player-detail" in rendered
    assert "角色 ID · 可框选复制" in rendered
    assert ">1</code>" in rendered
    assert "价值 <b>40</b>" in rendered
    assert "风险 <b>30</b>" in rendered
    assert 'class="vip-composite-score">70<' in rendered
    assert "--bar-width:100.0%" in rendered


def test_server_contact_panel_renders_ranked_server_rows() -> None:
    fake_st = _FakeStreamlit()

    _render_server_contact_chart(fake_st, _insight_rows())

    rendered = "".join(fake_st.markdowns)
    assert "vip-server-row" in rendered
    assert "区服待触达 Top 12" in rendered
    assert 'class="vip-server-name">S1<' in rendered
    assert 'class="vip-server-count">2<' in rendered
