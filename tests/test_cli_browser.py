"""Tests for CLI browser-open port polling helpers."""

import socket
import threading
import time

import pytest

from boulder.cli import schedule_browser_open, wait_for_port


def test_wait_for_port_returns_true_when_port_becomes_in_use():
    """Assert wait_for_port returns True when the target port is listening."""
    host, port = "127.0.0.1", 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, port))
    bound_port = sock.getsockname()[1]
    sock.listen(1)

    def _release_after_delay():
        time.sleep(0.2)
        sock.close()

    threading.Thread(target=_release_after_delay, daemon=True).start()
    assert wait_for_port(host, bound_port, timeout=2.0, poll_interval=0.05) is True


def test_wait_for_port_times_out_when_port_stays_free():
    """Assert wait_for_port returns False when the port never becomes bound."""
    host, port = "127.0.0.1", 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, port))
    free_port = sock.getsockname()[1]
    sock.close()
    assert wait_for_port(host, free_port, timeout=0.3, poll_interval=0.05) is False


def test_schedule_browser_open_waits_for_port(monkeypatch):
    """Assert schedule_browser_open opens the browser once the port is listening."""
    opened = []

    def fake_open(url):
        opened.append(url)

    monkeypatch.setattr("boulder.cli.webbrowser.open", fake_open)

    host, port = "127.0.0.1", 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, port))
    bound_port = sock.getsockname()[1]
    sock.listen(1)

    url = f"http://{host}:{bound_port}"
    schedule_browser_open(url, host, bound_port, timeout=2.0, poll_interval=0.05)
    time.sleep(0.5)
    sock.close()

    assert opened == [url]


def test_main_uses_schedule_browser_open_not_sync_open(monkeypatch):
    """Assert production main() schedules browser open instead of opening synchronously."""
    calls = {"sync_open": 0, "scheduled": 0}

    monkeypatch.setattr(
        "boulder.cli.webbrowser.open",
        lambda url: calls.__setitem__("sync_open", calls["sync_open"] + 1),
    )
    monkeypatch.setattr(
        "boulder.cli.schedule_browser_open",
        lambda url, host, port, **kwargs: calls.__setitem__(
            "scheduled", calls["scheduled"] + 1
        ),
    )
    monkeypatch.setattr("boulder.cli.is_port_in_use", lambda h, p: False)

    import types

    api_main = types.SimpleNamespace(_converter_class=None, _runner_class=None)
    monkeypatch.setitem(__import__("sys").modules, "boulder.api.main", api_main)

    import uvicorn

    monkeypatch.setattr(
        uvicorn, "run", lambda *a, **kw: (_ for _ in ()).throw(SystemExit(0))
    )

    import boulder.cli as cli

    with pytest.raises(SystemExit):
        cli.main([])

    assert calls["sync_open"] == 0
    assert calls["scheduled"] == 1


def test_dev_mode_schedules_vite_browser_open(monkeypatch, tmp_path):
    """Assert --dev mode schedules browser open for the Vite port instead of sleeping."""
    scheduled = []

    monkeypatch.setattr(
        "boulder.cli.schedule_browser_open",
        lambda url, host, port, **kwargs: scheduled.append((url, host, port)),
    )
    monkeypatch.setattr("boulder.cli.Path.exists", lambda self: True)
    monkeypatch.setattr("platform.system", lambda: "Windows")

    def fake_run(*args, **kwargs):
        return None

    monkeypatch.setattr("subprocess.run", fake_run)

    import types

    api_main = types.SimpleNamespace(_converter_class=None, _runner_class=None)
    monkeypatch.setitem(__import__("sys").modules, "boulder.api.main", api_main)

    import uvicorn

    monkeypatch.setattr(
        uvicorn, "run", lambda *a, **kw: (_ for _ in ()).throw(SystemExit(0))
    )

    import boulder.cli as cli

    with pytest.raises(SystemExit):
        cli.main(["--dev"])

    assert scheduled == [("http://localhost:5173", "127.0.0.1", 5173)]


def _stub_server(monkeypatch):
    """Make main() reach the uvicorn call and stop there."""
    import types

    monkeypatch.setattr("boulder.cli.schedule_browser_open", lambda *a, **kw: None)
    monkeypatch.setattr("boulder.cli.is_port_in_use", lambda h, p: False)
    api_main = types.SimpleNamespace(_converter_class=None, _runner_class=None)
    monkeypatch.setitem(__import__("sys").modules, "boulder.api.main", api_main)

    import uvicorn

    monkeypatch.setattr(
        uvicorn, "run", lambda *a, **kw: (_ for _ in ()).throw(SystemExit(0))
    )


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", "http://127.0.0.1:8050"),
        ("localhost", "http://localhost:8050"),
        # A wildcard bind accepts every interface but is not a destination a
        # browser can resolve: report loopback instead.
        ("0.0.0.0", "http://127.0.0.1:8050"),
        ("", "http://127.0.0.1:8050"),
        ("::", "http://[::1]:8050"),
    ],
)
def test_browsable_url_reports_a_reachable_address(host, expected):
    from boulder.cli import browsable_url

    assert browsable_url(host, 8050) == expected


def test_startup_prints_the_interface_url_without_verbose(monkeypatch, capsys):
    """A plain start must say where the interface is.

    Without --verbose uvicorn logs at warning level, so nothing else names the
    address -- and with --no-open no browser appears to reveal it either.
    """
    _stub_server(monkeypatch)

    import boulder.cli as cli

    with pytest.raises(SystemExit):
        cli.main(["--no-open", "--port", "8050"])

    assert "Open the interface at http://127.0.0.1:8050" in capsys.readouterr().out


def test_dev_mode_points_at_the_frontend_port_not_the_api(monkeypatch, capsys):
    """In --dev the interface is Vite's; the backend here only serves the API."""
    monkeypatch.setattr("boulder.cli.Path.exists", lambda self: True)
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: None)
    _stub_server(monkeypatch)

    import boulder.cli as cli

    with pytest.raises(SystemExit):
        cli.main(["--dev"])

    out = capsys.readouterr().out
    assert "Open the interface at http://localhost:5173" in out
