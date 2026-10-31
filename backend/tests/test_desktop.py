"""Desktop launcher (app/desktop.py): data-directory handling and the readiness
handshake the Tauri shell relies on."""
import json
import os
import socket
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from app import desktop

BACKEND = Path(__file__).resolve().parents[1]
SETTINGS_VARS = ("PROJECTS_DIR", "FRAME_CACHE_DIR", "REPORTS_DIR", "PERSIST_DB", "METADATA_DB_URL",
                 "SECRET_KEY", "SERVE_STATIC", "STATIC_DIR", "DEBUG", "HOST", "SFS_DESKTOP", "SFS_ENV_FILE")


def test_data_dirs_point_into_the_data_dir(tmp_path):
    env = desktop.desktop_environment(tmp_path, environ={})
    assert env["PROJECTS_DIR"] == str(tmp_path.resolve() / "projects")
    assert env["FRAME_CACHE_DIR"] == str(tmp_path.resolve() / "frame_cache")
    assert env["PERSIST_DB"] == str(tmp_path.resolve() / "reports_data" / "persist.duckdb")
    assert env["METADATA_DB_URL"] == "sqlite+aiosqlite:///" + (tmp_path.resolve() / "flow_studio.db").as_posix()
    assert env["HOST"] == "127.0.0.1" and env["SERVE_STATIC"] == "true" and env["SFS_DESKTOP"] == "1"
    assert env["SFS_ENV_FILE"] == str(tmp_path.resolve() / ".env")


def test_existing_settings_win(tmp_path):
    env = desktop.desktop_environment(tmp_path, environ={"PROJECTS_DIR": "/elsewhere", "SECRET_KEY": "k"})
    assert "PROJECTS_DIR" not in env and "SECRET_KEY" not in env
    assert not (tmp_path / desktop.SECRET_KEY_FILE).exists()


def test_secret_key_is_created_once_owner_only(tmp_path):
    from cryptography.fernet import Fernet

    first = desktop.desktop_environment(tmp_path, environ={})["SECRET_KEY"]
    second = desktop.desktop_environment(tmp_path, environ={})["SECRET_KEY"]
    assert first == second
    Fernet(first.encode())                                   # a valid key
    key_file = tmp_path / desktop.SECRET_KEY_FILE
    if os.name == "posix":
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_socket_is_local_only():
    sock = desktop.bind_local_socket()
    try:
        host, port = sock.getsockname()
        assert host == "127.0.0.1" and port > 0
    finally:
        sock.close()


def test_ready_line_format():
    assert desktop.ready_line(53817) == "SFS_READY port=53817"


def test_default_static_dir_is_next_to_main_py(monkeypatch, tmp_path):
    """Regression: the default pointed at backend/app/static, so single-container
    mode never served the frontend."""
    from app.core import app_factory

    static = BACKEND / "static"
    assert Path(app_factory.__file__).resolve().parents[2] / "static" == static


@pytest.fixture
def launched(tmp_path):
    """Start the launcher as the shell does and wait for its ready line."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text('<div id="root"></div>')
    env = {k: v for k, v in os.environ.items() if k not in SETTINGS_VARS}
    env["STATIC_DIR"] = str(static)
    env["PYTHONPATH"] = str(BACKEND)
    # Launched from a folder whose .env Settings would reject: it must be ignored
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    (cwd / ".env").write_text("NOT_AN_SFS_SETTING=1\n")
    proc = subprocess.Popen([sys.executable, "-m", "app.desktop", "--data-dir", str(tmp_path / "data")],
                            cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    deadline, line = time.time() + 60, ""
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line or line.startswith(desktop.READY_PREFIX):
            break
    yield proc, line, tmp_path / "data"
    if proc.poll() is None:
        proc.kill()
        proc.wait()


def test_handshake_serves_app_and_api_then_exits_on_stdin_eof(launched):
    proc, line, data = launched
    assert line.startswith("SFS_READY port="), line
    port = int(line.strip().split("port=")[1])

    caps = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/capabilities/", timeout=10))
    assert any(e["name"] == "pandas" for e in caps["engines"])
    assert b'id="root"' in urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).read()
    assert (data / "projects").is_dir() and (data / "frame_cache").is_dir()
    assert (data / desktop.SECRET_KEY_FILE).exists()

    # Not reachable on other interfaces: the socket is bound to 127.0.0.1 only
    with socket.socket() as s:
        s.settimeout(1)
        other = socket.gethostbyname(socket.gethostname())
        if other != "127.0.0.1" and not other.startswith("127."):
            assert s.connect_ex((other, port)) != 0

    proc.stdin.close()                                       # the shell went away
    assert proc.wait(timeout=15) == 0


def test_desktop_hides_reports(launched):
    """Desktop ships no Streamlit viewer, so the UI hides the Report node."""
    proc, line, _ = launched
    port = int(line.strip().split("port=")[1])
    caps = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/capabilities/", timeout=10))
    assert caps["features"]["desktop"] is True and caps["features"]["reports"] is False
