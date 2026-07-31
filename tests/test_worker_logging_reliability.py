import io
import logging

from optionbeacon.worker.logging_config import worker_log_handlers
from trade_repository import TradeRepository


def test_worker_info_uses_stdout_and_errors_use_stderr():
    stdout = io.StringIO()
    stderr = io.StringIO()
    logger = logging.Logger("worker-stream-test", level=logging.INFO)
    for handler in worker_log_handlers(stdout, stderr):
        logger.addHandler(handler)

    logger.info('{"event": "scan_complete"}')
    logger.warning('{"event": "provider_warning_summary"}')
    logger.error('{"event": "operational_error"}')

    assert "scan_complete" in stdout.getvalue()
    assert "provider_warning_summary" not in stdout.getvalue()
    assert "scan_complete" not in stderr.getvalue()
    assert "provider_warning_summary" in stderr.getvalue()
    assert "operational_error" in stderr.getvalue()


def test_repository_connection_ready_logs_once_by_default(tmp_path):
    events = []
    repository = TradeRepository(
        tmp_path / "state.db",
        database_url="",
        diagnostic_callback=events.append,
    )
    repository.list_opportunities()
    repository.list_open_trades()

    ready = [
        event for event in events if event["event"] == "repository_connection_ready"
    ]
    assert len(ready) == 1


def test_verbose_storage_diagnostics_opt_in(tmp_path):
    events = []
    repository = TradeRepository(
        tmp_path / "state.db",
        database_url="",
        diagnostic_callback=events.append,
        verbose_storage_diagnostics=True,
    )
    repository.list_opportunities()
    repository.list_open_trades()

    ready = [
        event for event in events if event["event"] == "repository_connection_ready"
    ]
    assert len(ready) >= 3
