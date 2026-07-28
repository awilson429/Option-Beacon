"""Deterministic card navigation for the OptionBeacon dashboard."""

from html import escape


MAIN_NAVIGATION = (
    "Trade Desk",
    "Opportunities",
    "After Hours",
    "History",
    "Tools",
    "Developer Tools",
)

NAVIGATION_SLUGS = {
    "Trade Desk": "trade-desk",
    "Opportunities": "opportunities",
    "After Hours": "after-hours",
    "History": "history",
    "Tools": "tools",
    "Developer Tools": "developer-tools",
}

CARD_NAVIGATION_CSS = """
<style>
.ob-nav-grid {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 0.75rem;
    margin: 0.75rem 0 1.5rem;
}
.ob-nav-card {
    align-items: center;
    background: #15191f;
    border: 1px solid #3a414b;
    border-radius: 0.75rem;
    color: #f3f4f6 !important;
    display: flex;
    font-size: 0.92rem;
    font-weight: 650;
    justify-content: center;
    min-height: 4.25rem;
    padding: 0.8rem 0.65rem;
    text-align: center;
    text-decoration: none !important;
    transition: border-color 120ms ease, background 120ms ease, transform 120ms ease;
}
.ob-nav-card:hover {
    background: #20252c;
    border-color: #c8a84e;
    color: #ffffff !important;
    transform: translateY(-1px);
}
.ob-nav-card-active {
    background: linear-gradient(135deg, #332b18, #211d14);
    border: 2px solid #d2ad4f;
    box-shadow: 0 0 0 1px rgba(210, 173, 79, 0.16);
    color: #f7df9a !important;
}
@media (max-width: 900px) {
    .ob-nav-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 600px) {
    .ob-nav-grid {
        gap: 0.55rem;
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .ob-nav-card {
        min-height: 3.75rem;
        padding: 0.65rem 0.5rem;
    }
}
@media (max-width: 360px) {
    .ob-nav-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
"""


def selected_navigation_page(query_params=None):
    """Resolve the requested page, defaulting safely to Trade Desk."""
    if query_params is None:
        import streamlit as st

        query_params = st.query_params
    params = query_params
    requested = params.get("page", NAVIGATION_SLUGS[MAIN_NAVIGATION[0]])
    if isinstance(requested, (list, tuple)):
        requested = requested[0] if requested else ""
    slug_to_page = {slug: page for page, slug in NAVIGATION_SLUGS.items()}
    return slug_to_page.get(str(requested), MAIN_NAVIGATION[0])


def navigation_markup(active_page):
    """Return app-controlled card markup with no generated Streamlit selectors."""
    cards = []
    for page in MAIN_NAVIGATION:
        active = page == active_page
        classes = "ob-nav-card ob-nav-card-active" if active else "ob-nav-card"
        current = ' aria-current="page"' if active else ""
        cards.append(
            f'<a class="{classes}" href="?page={NAVIGATION_SLUGS[page]}"'
            f'{current}>{escape(page)}</a>'
        )
    return '<nav class="ob-nav-grid" aria-label="Primary navigation">' + "".join(cards) + "</nav>"


def render_card_navigation(query_params=None):
    """Render the single navigation implementation used in every environment."""
    import streamlit as st

    active_page = selected_navigation_page(query_params)
    st.markdown(CARD_NAVIGATION_CSS, unsafe_allow_html=True)
    st.markdown(navigation_markup(active_page), unsafe_allow_html=True)
    return active_page


TOOLS_SECTIONS = ("Scanner Health",)
TRADE_DESK_SUBTITLE = (
    "Live alert validation, open-trade management, and system performance."
)
RECORDED_CANDIDATES_LABEL = "Recorded Candidates"

TRADE_DESK_SECTIONS = (
    "Today's Best Trade",
    "Open Positions Needing Attention",
    "Today's Scorecard",
    "Opened Alerts",
    "Active Edge",
    "Performance Details",
    "Grouped Performance",
    "Complete Trade History",
)

NO_OPEN_ALERTS_MESSAGE = "No entered trades are currently open."
NO_ACTIONABLE_OPPORTUNITY_MESSAGE = (
    "No actionable opportunity currently meets the entry requirements."
)
