import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import config as wf_config  # noqa: E402

SECRET_ENV = (
    "TAVILY_API_KEY",
    "TAVILY",
    "EXA_API_KEY",
    "EXA",
    "FIRECRAWL_API_KEY",
    "FIRECRAWL",
    "JINA_API_KEY",
    "JINA",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_MCP_TOKEN",
    "WF_BIN",
    "WF_VENV",
)


@pytest.fixture(autouse=True)
def isolate_local_config(monkeypatch, tmp_path):
    """默认不读取真实本地配置或密钥，避免测试污染。"""
    monkeypatch.setenv("WF_CONFIG", str(tmp_path / "missing-config.json"))
    monkeypatch.setattr(wf_config, "BACKUP_DIR", tmp_path / "backups")
    for name in SECRET_ENV:
        monkeypatch.delenv(name, raising=False)
