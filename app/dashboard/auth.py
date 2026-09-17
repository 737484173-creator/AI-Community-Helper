from __future__ import annotations

import hmac
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthResult:
    allowed: bool
    development_mode: bool = False


def verify_password(input_password: str, expected_password: str | None) -> AuthResult:
    if not expected_password:
        return AuthResult(allowed=True, development_mode=True)
    return AuthResult(
        allowed=hmac.compare_digest(input_password, expected_password),
        development_mode=False,
    )


def require_dashboard_auth(st, dashboard_password: str | None) -> bool:
    if "dashboard_authenticated" not in st.session_state:
        st.session_state.dashboard_authenticated = False

    if not dashboard_password:
        st.sidebar.warning("未配置后台密码，当前为本地开发模式。")
        st.session_state.dashboard_authenticated = True
        return True

    if st.session_state.dashboard_authenticated:
        if st.sidebar.button("退出登录", key="sidebar_logout"):
            st.session_state.dashboard_authenticated = False
            st.rerun()
        return True

    with st.container(key="auth_shell", border=True):
        st.markdown(
            """
            <div class="auth-brand-mark" aria-hidden="true">A</div>
            <div class="auth-eyebrow">AIDC WORKBENCH</div>
            <div class="auth-title">欢迎回来</div>
            <div class="auth-copy">登录 VIP Operation Center，继续处理社区运营工作。</div>
            """,
            unsafe_allow_html=True,
        )
        password = st.text_input("密码", type="password", placeholder="输入后台访问密码")
        if st.button("登录", type="primary", use_container_width=True):
            result = verify_password(password, dashboard_password)
            if result.allowed:
                st.session_state.dashboard_authenticated = True
                st.rerun()
            st.error("密码不正确。")
    return False
