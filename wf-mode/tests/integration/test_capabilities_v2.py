import importlib
import json
from pathlib import Path

from tools import repo_utils


def test_duckduckgo_html_parser_unwraps_uddg():
    from tools.adapters.web_search import adapter

    sample_html = """
    <html><body>
      <div class="result">
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fast-grep%2Fast-grep&amp;rut=1">ast-grep</a>
        <a class="result__snippet">A fast structural search tool.</a>
      </div>
      <div class="result">
        <a class="result__a" href="https://duckduckgo.com/y.js?ad_domain=foo">Sponsored Ad</a>
        <a class="result__snippet">Should be skipped</a>
      </div>
    </body></html>
    """
    results = adapter.parse_duckduckgo_html(sample_html, limit=5)
    assert len(results) == 1
    assert results[0]["title"] == "ast-grep"
    assert results[0]["url"] == "https://github.com/ast-grep/ast-grep"
    assert "structural search" in results[0]["snippet"]


def test_web_extract_direct_converts_github_blob_and_html(monkeypatch):
    from tools.adapters.web_extract import adapter

    assert (
        adapter.normalize_fetch_url("https://github.com/org/repo/blob/main/README.md")
        == "https://raw.githubusercontent.com/org/repo/main/README.md"
    )

    sample_html = """<!doctype html><html><head>
      <title>Demo Docs</title>
      <meta property="article:published_time" content="2026-10-01T00:00:00Z" />
      <script>console.log("ignore")</script>
    </head><body>
      <nav>Sidebar nav</nav>
      <main><h1>Hello WF</h1><p>Read <code>pyproject.toml</code> carefully.</p></main>
    </body></html>"""

    monkeypatch.setattr(adapter.http_client, "get_text", lambda url, **kwargs: sample_html)
    res = adapter.execute("extract", {"url": "https://example.com/docs"}, provider="direct")
    assert res["title"] == "Demo Docs"
    assert res["metadata"]["publishedTime"] == "2026-10-01T00:00:00Z"
    assert "# Hello WF" in res["text"]
    assert "`pyproject.toml`" in res["text"]
    assert "Sidebar nav" not in res["text"]
    assert "console.log" not in res["text"]


def test_repo_ingest_local_tree_read_readme_and_digest(tmp_path):
    from tools.adapters.repo_ingest import adapter

    (tmp_path / "README.md").write_text("# Sample Project\nGreat tool.", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\ndependencies = ["pyyaml>=6.0"]\n', encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def run():\n    return 42\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.js").write_text("ignored", encoding="utf-8")

    tree = adapter.execute("tree", {"path": str(tmp_path)}, provider="local")
    assert "src/main.py" in tree["files"]
    assert all("node_modules" not in f for f in tree["files"])
    assert "Python" in tree["languages"]

    read = adapter.execute("read", {"path": str(tmp_path), "file": "src/main.py", "startLine": 1, "endLine": 2}, provider="local")
    assert "1: def run():" in read["content"]
    assert "2:     return 42" in read["content"]

    digest = adapter.execute("ingest", {"path": str(tmp_path)}, provider="github_api")
    assert digest["source"] == "local"
    assert "Sample Project" in digest["digest"]


def test_repo_health_computes_verdict_and_flags(monkeypatch):
    from tools.adapters.repo_health import adapter

    def fake_get_json(url, **kwargs):
        return {
            "full_name": "acme/demo",
            "html_url": "https://github.com/acme/demo",
            "archived": False,
            "stargazers_count": 1200,
            "forks_count": 80,
            "open_issues_count": 12,
            "pushed_at": "2020-01-01T00:00:00Z",
            "license": {"spdx_id": "AGPL-3.0"},
        }

    def fake_get_json_any(url, **kwargs):
        if url.endswith("/releases"):
            return []
        return [
            {"commit": {"author": {"date": "2020-01-01T00:00:00Z", "name": "solo"}}, "author": {"login": "solo"}}
            for _ in range(6)
        ]

    monkeypatch.setattr(adapter.http_client, "get_json", fake_get_json)
    monkeypatch.setattr(adapter.http_client, "get_json_any", fake_get_json_any)

    res = adapter.execute("analyze", {"repo": "acme/demo"})
    assert res["verdict"] == "stale"
    assert res["licenseCategory"] == "strong-copyleft"
    assert "STALE_365D" in res["riskFlags"]
    assert "STRONG_COPYLEFT" in res["riskFlags"]
    assert "NO_RELEASES" in res["riskFlags"]
    assert "LOW_BUS_FACTOR" in res["riskFlags"]


def test_package_meta_and_security_and_license_sbom(tmp_path, monkeypatch):
    from tools.adapters.package_meta import adapter as meta_adapter
    from tools.adapters.package_security import adapter as sec_adapter
    from tools.adapters.license_sbom import adapter as lic_adapter

    # package_meta PyPI mock
    monkeypatch.setattr(
        meta_adapter.http_client,
        "get_json",
        lambda url, **kw: {
            "info": {"name": "httpx", "version": "0.28.1", "summary": "HTTP client", "license": "BSD-3-Clause", "project_urls": {"Source": "https://github.com/encode/httpx"}},
            "releases": {"0.28.1": [{"upload_time_iso_8601": "2026-01-01T00:00:00Z"}]},
        },
    )
    pkg_res = meta_adapter.execute("lookup", {"package": "httpx", "ecosystem": "pypi"})
    assert pkg_res["package"]["version"] == "0.28.1"
    assert pkg_res["package"]["license"] == "BSD-3-Clause"

    # 本地项目准备 MIT LICENSE + requirements.txt + package.json
    (tmp_path / "LICENSE").write_text("Permission is hereby granted, free of charge, to any person obtaining a copy", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n# comment\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"lodash": "^4.17.20"}}), encoding="utf-8")

    sbom = lic_adapter.execute("scan", {"path": str(tmp_path)})
    assert sbom["license"] == "MIT"
    assert sbom["licenseCategory"] == "permissive"
    assert sbom["dependencyCount"] == 2

    # OSV querybatch mock
    def fake_post_json(url, body, **kw):
        if url.endswith("/querybatch"):
            return {"results": [{"vulns": [{"id": "GHSA-1234"}]}, {"vulns": []}]}
        return {"vulns": [{"id": "GHSA-1234", "summary": "Demo vuln"}]}

    monkeypatch.setattr(sec_adapter.http_client, "post_json", fake_post_json)
    monkeypatch.setattr(
        sec_adapter.http_client,
        "get_json",
        lambda url, **kw: {"id": "GHSA-1234", "summary": "Demo vuln", "aliases": ["CVE-2024-0001"], "database_specific": {"severity": "HIGH"}, "affected": []},
    )
    scan = sec_adapter.execute("scan", {"path": str(tmp_path)})
    assert scan["vulnerablePackages"] == 1
    assert scan["vulnerabilities"][0]["id"] == "GHSA-1234"
    assert "CVE-2024-0001" in scan["vulnerabilities"][0]["aliases"]


def test_dependency_graph_and_structural_search(tmp_path):
    from tools.adapters.dependency_graph import adapter as dep_adapter
    from tools.adapters.structural_search import adapter as str_adapter

    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text("import yaml\nimport app.b\ndef alpha():\n    pass\n", encoding="utf-8")
    (pkg / "b.py").write_text("import app.a\nclass Beta:\n    def work(self):\n        pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("import app.a\nif __name__ == '__main__':\n    pass\n", encoding="utf-8")

    graph = dep_adapter.execute("analyze", {"path": str(tmp_path)})
    assert "Python" in graph["languages"]
    assert "main.py" in graph["entrypoints"]
    assert graph["edgeCount"] >= 3
    assert any(d["name"] == "yaml" for d in graph["externalDependencies"])
    assert graph["circularDependencies"], "应能检测 app.a <-> app.b 循环依赖"

    sym = str_adapter.execute("symbols", {"path": str(tmp_path)}, provider="builtin")
    names = {s["name"] for s in sym["symbols"]}
    assert {"alpha", "Beta"}.issubset(names)

    found = str_adapter.execute("search", {"path": str(tmp_path), "pattern": "def alpha", "lang": "python"}, provider="builtin")
    assert found["count"] == 1
    assert found["matches"][0]["file"].endswith("a.py")
