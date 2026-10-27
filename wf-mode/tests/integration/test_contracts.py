import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"


def load_schema(name: str) -> dict:
    return json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def assert_valid(obj: dict, schema_name: str) -> None:
    validator = Draft202012Validator(load_schema(schema_name))
    errors = sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def assert_invalid(obj: dict, schema_name: str) -> None:
    validator = Draft202012Validator(load_schema(schema_name))
    assert list(validator.iter_errors(obj))


def test_registry_and_pipeline_match_schema():
    assert_valid(load_yaml(ROOT / "registry.yaml"), "registry.schema.json")
    assert_valid(load_yaml(ROOT / "pipelines" / "wf-retrieval" / "pipeline.yaml"), "pipeline.schema.json")


@pytest.mark.parametrize(
    "slot",
    ["web_search", "web_extract", "project_search"],
)
def test_adapter_manifests_match_schema(slot: str):
    manifest = load_yaml(ROOT / "tools" / "adapters" / slot / "manifest.yaml")
    assert_valid(manifest, "adapter-manifest.schema.json")


def test_run_valid_and_invalid():
    assert_valid(load_json(FIXTURES / "run.valid.json"), "run.schema.json")
    assert_invalid(load_json(FIXTURES / "run.invalid.json"), "run.schema.json")


def test_evidence_valid_and_invalid():
    assert_valid(load_json(FIXTURES / "evidence.valid.json"), "evidence.schema.json")
    assert_invalid(load_json(FIXTURES / "evidence.invalid.json"), "evidence.schema.json")


def test_envelope_valid_and_invalid():
    assert_valid(load_json(FIXTURES / "envelope.valid.json"), "tool-envelope.schema.json")
    assert_invalid(load_json(FIXTURES / "envelope.invalid.json"), "tool-envelope.schema.json")
