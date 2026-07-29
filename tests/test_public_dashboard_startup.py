from pathlib import Path

from developer_tools import HOSTED_SECRET_NAMES


def test_app_opens_directly_to_dashboard():
    source = Path("app.py").read_text(encoding="utf-8")

    assert 'type="password"' not in source
    assert "st.stop()" not in source
    assert "render_header()" in source
    assert "active_page = render_sidebar_navigation(" in source


def test_hosted_configuration_requires_provider_secrets_only():
    assert HOSTED_SECRET_NAMES == (
        "TRADIER_ACCESS_TOKEN",
        "FINNHUB_API_KEY",
    )
