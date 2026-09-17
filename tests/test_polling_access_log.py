"""Timer-driven polling must not bury the access log."""

from __future__ import annotations

import logging

import pytest

from boulder.verbose_utils import quiet_polling_access_logs


@pytest.fixture
def access_logger():
    logger = logging.getLogger("uvicorn.access")
    saved = list(logger.filters)
    logger.filters.clear()
    yield logger
    logger.filters.clear()
    logger.filters.extend(saved)


def _kept(logger: logging.Logger, message: str) -> bool:
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, message, None, None
    )
    return all(f.filter(record) for f in logger.filters)


def test_polling_lines_are_dropped_and_real_requests_kept(access_logger):
    """One request per second for minutes leaves nothing else readable."""
    quiet_polling_access_logs()

    assert not _kept(access_logger, '- "GET /api/sweep/status HTTP/1.1" 200 OK')
    assert not _kept(
        access_logger, '- "GET /api/scenarios/focus/stream HTTP/1.1" 200 OK'
    )
    # Anything the user actually did still shows.
    assert _kept(access_logger, '- "POST /api/sweep/run HTTP/1.1" 200 OK')
    assert _kept(access_logger, '- "POST /api/configs/upload HTTP/1.1" 200 OK')
    assert _kept(access_logger, '- "GET /api/sweep HTTP/1.1" 500 Internal Server Error')


def test_installing_twice_adds_one_filter(access_logger):
    quiet_polling_access_logs()
    quiet_polling_access_logs()

    assert len(access_logger.filters) == 1


def test_opt_out_keeps_every_line(access_logger, monkeypatch):
    """For debugging the polling itself."""
    monkeypatch.setenv("BOULDER_LOG_POLLING", "1")

    quiet_polling_access_logs()

    assert access_logger.filters == []
