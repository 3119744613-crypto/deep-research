"""专用容器入口必须显式初始化，且不能覆盖或暴露配置。"""

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from document_research.config import init_config

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def entrypoint(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "document_research_container", ROOT / "docker/document-research/entrypoint.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DATA_DIR", tmp_path / "private-data")
    original_umask = os.umask(0o077)
    try:
        yield module
    finally:
        os.umask(original_umask)


def test_container_init_does_not_log_or_replace_existing_token(
    entrypoint, monkeypatch, capsys
):
    monkeypatch.setattr(sys, "argv", ["container-entrypoint.py", "init"])
    entrypoint.main()
    path = entrypoint.DATA_DIR / "config.json"
    initial = path.read_bytes()
    token = json.loads(initial)["tokens"]["local"]
    output = capsys.readouterr()
    assert token not in output.out + output.err
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(entrypoint.DATA_DIR.stat().st_mode) == 0o700

    with pytest.raises(SystemExit) as error:
        entrypoint.main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert token not in output.out + output.err
    assert path.read_bytes() == initial


def test_container_init_refuses_repository_data(entrypoint, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["container-entrypoint.py", "init"])
    monkeypatch.setattr(entrypoint, "DATA_DIR", ROOT)
    with pytest.raises(SystemExit) as error:
        entrypoint.main()
    assert error.value.code == 2


def test_container_serve_requires_explicit_config(entrypoint, monkeypatch):
    import uvicorn

    run = Mock()
    monkeypatch.setattr(uvicorn, "run", run)
    monkeypatch.setattr(sys, "argv", ["container-entrypoint.py", "serve"])
    with pytest.raises(SystemExit) as error:
        entrypoint.main()
    assert error.value.code == 2
    assert not entrypoint.DATA_DIR.exists()
    run.assert_not_called()


def test_container_serve_uses_dedicated_authenticated_app(entrypoint, monkeypatch):
    import uvicorn

    config_path = init_config(entrypoint.DATA_DIR)
    token = json.loads(config_path.read_text())["tokens"]["local"]
    run = Mock()
    monkeypatch.setattr(uvicorn, "run", run)
    monkeypatch.setattr(sys, "argv", ["container-entrypoint.py"])
    entrypoint.main()
    run.assert_called_once()
    assert run.call_args.kwargs == {
        "host": "0.0.0.0",
        "port": 4198,
        "workers": 1,
        "access_log": False,
    }
    app = run.call_args.args[0]
    with TestClient(app) as client:
        assert client.get("/document-research-api/health").status_code == 200
        assert client.get("/document-research-api/session").status_code == 401
        assert client.get(
            "/document-research-api/session",
            headers={"Authorization": "Bearer " + token},
        ).json() == {"user": "local"}
    assert (entrypoint.DATA_DIR / "document-research.sqlite3").exists()
