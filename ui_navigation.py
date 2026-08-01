"""Persistent, native-sidebar navigation for the OptionBeacon workspace."""

from html import escape


MAIN_NAVIGATION = (
    "Trade Desk",
    "Positions",
    "Journal",
    "Developer Tools",
)

NAVIGATION_SLUGS = {
    "Trade Desk": "trade-desk",
    "Positions": "positions",
    "Journal": "journal",
    "Developer Tools": "developer-tools",
}

NAVIGATION_ICONS = {
    "Trade Desk": "◎",
    "Positions": "▣",
    "Journal": "▤",
    "Developer Tools": "◇",
}

SIDEBAR_CSS = """
<style>
[data-testid="stSidebar"] {
    border-right: 1px solid rgba(255,255,255,.11);
    background: #0b0f14;
}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    padding-top: .8rem;
}
[data-testid="stSidebar"] div[role="radiogroup"] {
    gap: .3rem;
}
[data-testid="stSidebar"] div[role="radiogroup"] label {
    border: 1px solid transparent;
    border-radius: .65rem;
    padding: .55rem .65rem;
    transition: background 120ms ease, border-color 120ms ease;
}
[data-testid="stSidebar"] div[role="radiogroup"] label:hover {
    background: rgba(255,255,255,.045);
    border-color: rgba(216,179,90,.35);
}
[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
    background: rgba(216,179,90,.12);
    border-color: rgba(216,179,90,.72);
}
.ob-side-brand {
    border-bottom:1px solid rgba(255,255,255,.1);
    margin:0 0 .8rem; padding:.2rem .15rem .8rem;
}
.ob-side-brand-name {color:#f4f5f7;font-size:1.05rem;font-weight:800;}
.ob-side-brand-sub {color:#9da5af;font-size:.72rem;margin-top:.15rem;}
.ob-side-status {
    align-items:center; display:flex; flex-wrap:wrap; gap:.35rem;
    margin:.2rem 0 .8rem;
}
.ob-side-badge {
    border:1px solid #3a414b;border-radius:999px;color:#c8cdd4;
    font-size:.68rem;font-weight:750;padding:.22rem .45rem;text-transform:uppercase;
}
.ob-side-badge-open {border-color:#4ca977;color:#70d39b;}
.ob-side-badge-closed {border-color:#6b737e;color:#b5bcc5;}
.ob-side-badge-env {border-color:#c8a84e;color:#e0c56f;}
</style>
"""

CARD_NAVIGATION = (
    "Trade Desk",
    "Opportunities",
    "After Hours",
    "History",
    "Tools",
    "Developer Tools",
)

CARD_NAVIGATION_SLUGS = {
    "Trade Desk": "trade-desk",
    "Opportunities": "opportunities",
    "After Hours": "after-hours",
    "History": "history",
    "Tools": "tools",
    "Developer Tools": "developer-tools",
}

DESKTOP_NAVIGATION_COLUMNS = 6

CARD_NAVIGATION_CSS = """
<style>
.ob-nav-grid {
    height: 0;
}
div[class*="st-key-ob_nav_"] button {
    align-items: center;
    background: #15191f;
    border: 1px solid #3a414b;
    border-radius: 0.55rem;
    color: #f3f4f6 !important;
    display: flex;
    justify-content: center;
    height: 2.75rem;
    min-height: 2.75rem;
    padding: 0.45rem 0.65rem;
    text-align: center;
    transition: border-color 120ms ease, background 120ms ease, transform 120ms ease;
    width: 100%;
}
div[class*="st-key-ob_nav_"] button p {
    color: #f3f4f6 !important;
    font-size: 0.86rem;
    font-weight: 650;
    line-height: 1;
    margin: 0;
    white-space: nowrap;
}
div[class*="st-key-ob_nav_"] button:hover {
    background: #20252c;
    border-color: #c8a84e;
    color: #ffffff !important;
    transform: translateY(-1px);
}
div[class*="st-key-ob_nav_"] button:hover p {
    color: #ffffff !important;
}
div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-ob_nav_"]) {
    align-items: stretch;
    flex-wrap: nowrap;
    gap: 0.5rem;
    margin: 0.4rem 0 0.7rem;
    max-width: 100%;
    overflow: hidden;
}
div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-ob_nav_"])
    > div[data-testid="stColumn"] {
    min-width: 0;
}
@media (max-width: 760px) {
    div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-ob_nav_"]) {
        flex-wrap: wrap;
        overflow: visible;
    }
    div[data-testid="stHorizontalBlock"]:has(div[class*="st-key-ob_nav_"])
        > div[data-testid="stColumn"] {
        flex: 1 1 9rem;
        width: auto !important;
    }
    div[class*="st-key-ob_nav_"] button {
        height: 2.75rem;
        min-height: 2.75rem;
        padding: 0.45rem 0.5rem;
    }
}
</style>
"""


def selected_navigation_page(query_params=None, session_state=None):
    """Resolve navigation without resetting an existing valid session selection."""
    if session_state is not None:
        selected = session_state.get("ob_primary_page")
        if selected in MAIN_NAVIGATION:
            return selected
    if query_params is None:
        return MAIN_NAVIGATION[0]
    requested = query_params.get("page", NAVIGATION_SLUGS[MAIN_NAVIGATION[0]])
    if isinstance(requested, (list, tuple)):
        requested = requested[0] if requested else ""
    aliases = {
        "history": "Journal",
        "opportunities": "Trade Desk",
        "after-hours": "Trade Desk",
        "tools": "Developer Tools",
    }
    slug_to_page = {slug: page for page, slug in NAVIGATION_SLUGS.items()}
    return slug_to_page.get(str(requested), aliases.get(str(requested), MAIN_NAVIGATION[0]))


def active_card_workspace(session_state):
    """Return the active internal workspace, initializing a safe default."""
    selected = session_state.get("active_workspace")
    if selected not in CARD_NAVIGATION:
        selected = CARD_NAVIGATION[0]
        session_state["active_workspace"] = selected
    return selected


def set_active_workspace(workspace, session_state):
    """Select one internal workspace without changing the application route."""
    if workspace in CARD_NAVIGATION:
        session_state["active_workspace"] = workspace


def _card_key(workspace):
    return "ob_nav_" + workspace.lower().replace(" ", "_")


def _active_card_css(workspace):
    key = _card_key(workspace)
    return f"""
<style>
div.st-key-{key} button {{
    background: #292415;
    border: 1px solid #d2ad4f;
    box-shadow: inset 0 -2px 0 rgba(210, 173, 79, 0.65) !important;
    color: #f7df9a !important;
}}
div.st-key-{key} button p {{
    color: #f7df9a !important;
    font-weight: 650;
}}
</style>
"""


def render_card_navigation(st_module=None):
    """Render internal card controls backed by Streamlit session state."""
    if st_module is None:
        import streamlit as st_module

    active_page = active_card_workspace(st_module.session_state)
    st_module.markdown(
        CARD_NAVIGATION_CSS + _active_card_css(active_page),
        unsafe_allow_html=True,
    )

    navigation_row = st_module.columns(DESKTOP_NAVIGATION_COLUMNS)
    for column, workspace in zip(navigation_row, CARD_NAVIGATION):
        column.button(
            workspace,
            key=_card_key(workspace),
            on_click=set_active_workspace,
            args=(workspace, st_module.session_state),
            use_container_width=True,
        )
    return active_card_workspace(st_module.session_state)


def sidebar_brand_markup(market_open, environment):
    market_label = "Market Open" if market_open else "Market Closed"
    market_class = "ob-side-badge-open" if market_open else "ob-side-badge-closed"
    return (
        '<div class="ob-side-brand">'
        '<div class="ob-side-brand-name">OptionBeacon</div>'
        '<div class="ob-side-brand-sub">Trade decision workspace</div></div>'
        '<div class="ob-side-status">'
        f'<span class="ob-side-badge {market_class}">{escape(market_label)}</span>'
        f'<span class="ob-side-badge ob-side-badge-env">{escape(environment)}</span>'
        "</div>"
    )


def render_sidebar_navigation(
    *,
    market_open=False,
    environment="Development",
    build_text=None,
    query_params=None,
    st_module=None,
):
    """Render one mobile-safe, Streamlit-native primary navigation control."""
    if st_module is None:
        import streamlit as st_module

    params = st_module.query_params if query_params is None else query_params
    requested = selected_navigation_page(params)
    requested_slug = NAVIGATION_SLUGS[requested]
    last_query_slug = st_module.session_state.get("_ob_primary_query_slug")
    current = st_module.session_state.get("ob_primary_page")
    if current not in MAIN_NAVIGATION or (
        last_query_slug is not None and requested_slug != last_query_slug
    ):
        st_module.session_state["ob_primary_page"] = requested
    st_module.session_state["_ob_primary_query_slug"] = requested_slug

    def sync_query():
        selected_page = st_module.session_state["ob_primary_page"]
        selected_slug = NAVIGATION_SLUGS[selected_page]
        st_module.session_state["_ob_primary_query_slug"] = selected_slug
        if query_params is None:
            st_module.query_params["page"] = selected_slug

    sidebar = st_module.sidebar
    sidebar.markdown(SIDEBAR_CSS, unsafe_allow_html=True)
    sidebar.markdown(
        sidebar_brand_markup(market_open, environment),
        unsafe_allow_html=True,
    )
    selected = sidebar.radio(
        "Primary workspace",
        MAIN_NAVIGATION,
        format_func=lambda page: f"{NAVIGATION_ICONS[page]}  {page}",
        key="ob_primary_page",
        label_visibility="collapsed",
        on_change=sync_query,
    )
    sidebar.divider()
    sidebar.button("Refresh data", key="ob_refresh_data", use_container_width=True)
    with sidebar.expander("Settings & build"):
        sidebar.caption(f"Environment: {environment}")
        if build_text:
            sidebar.caption(build_text)

    if query_params is None:
        try:
            selected_slug = NAVIGATION_SLUGS[selected]
            if st_module.query_params.get("page") != selected_slug:
                st_module.query_params["page"] = selected_slug
            st_module.session_state["_ob_primary_query_slug"] = selected_slug
        except (AttributeError, TypeError):
            pass
    return selected


TOOLS_SECTIONS = ("Scanner Health",)
TRADE_DESK_SUBTITLE = "Focused live setup, entry, risk, and target decisions."
RECORDED_CANDIDATES_LABEL = "Recorded Candidates"

TRADE_DESK_SECTIONS = (
    "Market Status",
    "Best Developing Setup",
    "Quick Actions",
    "Open Positions",
    "Recent Signals",
)

NO_OPEN_ALERTS_MESSAGE = "No entered trades are currently open."
NO_ACTIONABLE_OPPORTUNITY_MESSAGE = (
    "No actionable opportunity currently meets the entry requirements."
)
