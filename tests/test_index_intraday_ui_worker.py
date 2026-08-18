from pathlib import Path
from ui_navigation import CARD_NAVIGATION

def test_intraday_is_second_destination_and_streamlit_is_read_only():
    assert CARD_NAVIGATION[2] == "SPY / QQQ"
    source = Path("intraday_page.py").read_text(encoding="utf-8")
    assert "option_chain" not in source and "urlopen" not in source
    assert "save_signal" not in source and "open_variants" not in source

def test_worker_is_separate_and_no_live_order_path_exists():
    broad = Path("optionbeacon/worker/run.py").read_text(encoding="utf-8")
    worker = Path("optionbeacon/worker/intraday.py").read_text(encoding="utf-8")
    assert "run_intraday_cycle" not in broad
    assert "submit_order" not in worker and "Robinhood" not in worker
