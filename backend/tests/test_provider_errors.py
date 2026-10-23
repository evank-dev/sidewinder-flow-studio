"""Provider connection failures must say how to fix them."""
from types import SimpleNamespace

import httpx

from app.services import agent_provider_service as svc


def _p(base, kind="ollama"):
    return SimpleNamespace(base_url=base, provider_type=kind)


def test_localhost_in_docker_points_to_host_docker_internal(monkeypatch):
    monkeypatch.setattr(svc.os.path, "exists", lambda p: p == "/.dockerenv")
    msg = svc.explain_error(_p("http://localhost:11434"), httpx.ConnectError("refused"))
    assert "host.docker.internal:11434" in msg


def test_host_docker_internal_points_to_ollama_host():
    msg = svc.explain_error(_p("http://host.docker.internal:11434"), httpx.ConnectError("refused"))
    assert "OLLAMA_HOST=0.0.0.0:11434" in msg


def test_other_errors_pass_through():
    assert svc.explain_error(_p("http://x:1"), ValueError("bad model")) == "bad model"
