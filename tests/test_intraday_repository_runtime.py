import json
import logging
from contextlib import contextmanager

from intraday_execution import IntradayRepository
from intraday_page import intraday_dashboard_model, render_intraday_page
from trade_repository import RepositoryUnavailable, TradeRepository


class Area:
    def markdown(self, *args, **kwargs): pass
    def caption(self, *args, **kwargs): pass
    def metric(self, *args, **kwargs): pass
    def dataframe(self, *args, **kwargs): pass


class FakeStreamlit(Area):
    def __init__(self): self.messages = []
    def columns(self, count): return [Area() for _ in range(count)]
    def warning(self, message): self.messages.append(("warning", message))
    def info(self, message): self.messages.append(("info", message))


def test_valid_repository_and_existing_intraday_data_render(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    IntradayRepository(repository)
    model = intraday_dashboard_model(repository)
    assert model["persistence_state"] == "AVAILABLE"
    assert model["symbols"] == {"SPY": None, "QQQ": None}
    st = FakeStreamlit(); render_intraday_page(repository, st)
    assert not [message for kind, message in st.messages if kind == "warning"]


def test_missing_worker_tables_is_clean_not_initialized_state(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    model = intraday_dashboard_model(repository)
    assert model["persistence_state"] == "NOT_INITIALIZED"
    assert set(model["missing_tables"]) == {
        "intraday_signals", "intraday_paper_trades",
        "intraday_paper_journal", "intraday_runtime_state",
    }
    st = FakeStreamlit(); render_intraday_page(repository, st)
    assert st.messages == [("info", "Intraday storage has not been initialized by the worker yet.")]


def test_real_read_failure_logs_sanitized_structure(caplog, monkeypatch):
    class BrokenRepository:
        backend = "postgresql"
        @contextmanager
        def connection(self):
            try:
                raise ValueError("postgresql://user:secret@db.example/private")
            except ValueError as cause:
                raise RepositoryUnavailable("Trade repository unavailable: ValueError") from cause
            yield
    monkeypatch.setenv("DATABASE_URL", "configured-but-never-logged")
    st = FakeStreamlit()
    with caplog.at_level(logging.ERROR, logger="intraday_page"):
        render_intraday_page(BrokenRepository(), st)
    record = next(json.loads(item.message) for item in caplog.records
                  if "intraday_repository_unavailable" in item.message)
    assert record["event"] == "intraday_repository_unavailable"
    assert record["database_url_present"] is True
    assert record["repository_construction_succeeded"] is True
    assert record["schema_read_probe_succeeded"] is False
    assert "secret" not in record["sanitized_message"]


def test_streamlit_intraday_path_is_read_only_and_reuses_main_repository():
    page = open("intraday_page.py", encoding="utf-8").read()
    app = open("app.py", encoding="utf-8").read()
    for forbidden in ("initialize=True", ".initialize(", "save_signal(", "open_variants(", "CREATE TABLE", "INSERT INTO", "UPDATE "):
        assert forbidden not in page
    assert 'render_intraday_page(trade_state.get("repository"))' in app
    assert "dashboard_database_url" in app
