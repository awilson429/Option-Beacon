"""Local-only Streamlit entry point for the isolated Trade Desk UI preview."""

import streamlit as st

from ui.trade_desk_preview import (
    configure_preview_page,
    preview_data,
    render_trade_desk_preview,
)


configure_preview_page(st)
render_trade_desk_preview(st, preview_data())
