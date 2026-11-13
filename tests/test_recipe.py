# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import base64
import gzip
import json
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest
from typer.testing import CliRunner

from tft.cli.tool import app
from tft.cli.utils import recipe_to_request_value

RECIPE = "discover:\n  - how: fmf\nexecute:\n  how: tmt\n"
REQUEST_ID = "40cafaa3-0efa-4abf-a20b-a6ad87e84527"

runner = CliRunner()


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TESTING_FARM_API_TOKEN", "token")


@pytest.fixture
def recipe_file(tmp_path: Path) -> Path:
    path = tmp_path / "recipe.yaml"
    path.write_text(RECIPE)
    return path


def _request_args(*extra: str) -> List[str]:
    return [
        "request",
        "--git-url",
        "https://example.com/repo",
        "--git-ref",
        "main",
        "--compose",
        "Fedora",
        "--dry-run",
        *extra,
    ]


def _dry_run_json(output: str) -> Dict[str, Any]:
    return json.loads(output[output.index("{") :])  # noqa: E203


def _restart_args(*extra: str) -> List[str]:
    return ["restart", "--dry-run", *extra, REQUEST_ID]


def _stored_request(test: Dict[str, Any]) -> mock.Mock:
    stored = {
        "environments_requested": [{"arch": "x86_64", "os": {"compose": "Fedora"}}],
        "test": {"fmf": {"url": "https://example.com/repo", "ref": "main", **test}},
        "settings": {},
    }
    response = mock.Mock(status_code=200)
    response.json.return_value = stored
    session = mock.Mock()
    session.get.return_value = response
    return session


def _restart(args: List[str], test: Dict[str, Any]) -> Any:
    with mock.patch("tft.cli.commands.requests.Session", return_value=_stored_request(test)):
        return runner.invoke(app, args)


def test_url_passthrough() -> None:
    url = "https://example.com/recipe.yaml.gz"

    assert recipe_to_request_value(url) == url
    assert recipe_to_request_value("http://example.com/recipe.yaml") == "http://example.com/recipe.yaml"


def test_local_file_is_gzipped_and_base64_encoded(recipe_file: Path) -> None:
    value = recipe_to_request_value(str(recipe_file))

    assert gzip.decompress(base64.b64decode(value)).decode() == RECIPE


def test_gzipped_local_file_is_not_gzipped_again(tmp_path: Path) -> None:
    path = tmp_path / "recipe.yaml.gz"
    path.write_bytes(gzip.compress(RECIPE.encode()))

    value = recipe_to_request_value(str(path))

    assert gzip.decompress(base64.b64decode(value)).decode() == RECIPE


def test_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, _request_args("--recipe", str(tmp_path / "missing.yaml")))

    assert result.exit_code == 255
    assert "does not exist" in result.output


def test_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("\n")

    result = runner.invoke(app, _request_args("--recipe", str(empty)))

    assert result.exit_code == 255
    assert "is empty" in result.output


def test_request_with_url() -> None:
    result = runner.invoke(app, _request_args("--recipe", "https://example.com/recipe.yaml"))

    assert result.exit_code == 0, result.output
    fmf = _dry_run_json(result.output)["test"]["fmf"]
    assert fmf["recipe"] == "https://example.com/recipe.yaml"
    assert fmf["url"] == "https://example.com/repo"
    assert fmf["ref"] == "main"


def test_request_with_local_file(recipe_file: Path) -> None:
    result = runner.invoke(app, _request_args("--recipe", str(recipe_file)))

    assert result.exit_code == 0, result.output
    recipe = _dry_run_json(result.output)["test"]["fmf"]["recipe"]
    assert gzip.decompress(base64.b64decode(recipe)).decode() == RECIPE


def test_request_with_gzipped_local_file(tmp_path: Path) -> None:
    path = tmp_path / "recipe.yaml.gz"
    path.write_bytes(gzip.compress(RECIPE.encode()))

    result = runner.invoke(app, _request_args("--recipe", str(path)))

    assert result.exit_code == 0, result.output
    recipe = _dry_run_json(result.output)["test"]["fmf"]["recipe"]
    assert gzip.decompress(base64.b64decode(recipe)).decode() == RECIPE


def test_restart_with_gzipped_local_file(tmp_path: Path) -> None:
    path = tmp_path / "recipe.yaml.gz"
    path.write_bytes(gzip.compress(RECIPE.encode()))

    result = _restart(_restart_args("--recipe", str(path)), {})

    assert result.exit_code == 0, result.output
    recipe = _dry_run_json(result.output)["test"]["fmf"]["recipe"]
    assert gzip.decompress(base64.b64decode(recipe)).decode() == RECIPE


def test_restart_with_local_file(recipe_file: Path) -> None:
    result = _restart(_restart_args("--recipe", str(recipe_file)), {})

    assert result.exit_code == 0, result.output
    recipe = _dry_run_json(result.output)["test"]["fmf"]["recipe"]
    assert gzip.decompress(base64.b64decode(recipe)).decode() == RECIPE


@pytest.mark.parametrize("command", [["run", "--dry-run", "--", "true"], ["reserve", "--dry-run"]])
def test_request_does_not_leak_run_or_reserve_test(command: List[str]) -> None:
    first = runner.invoke(app, command)
    assert first.exit_code == 0, first.output

    result = runner.invoke(app, _request_args("--recipe", "https://example.com/recipe.yaml"))

    assert result.exit_code == 0, result.output
    fmf = _dry_run_json(result.output)["test"]["fmf"]
    assert fmf.get("name") is None
    assert fmf["recipe"] == "https://example.com/recipe.yaml"
    assert fmf["url"] == "https://example.com/repo"


def test_request_without_recipe() -> None:
    result = runner.invoke(app, _request_args())

    assert result.exit_code == 0, result.output
    assert "recipe" not in _dry_run_json(result.output)["test"]["fmf"]


@pytest.mark.parametrize(
    "option", [("--plan", "p"), ("--plan-filter", "tag:x"), ("--test", "t"), ("--test-filter", "tag:x")]
)
def test_request_conflicting_options(option: Any) -> None:
    result = runner.invoke(app, _request_args("--recipe", "https://example.com/r.yaml", *option))

    assert result.exit_code == 255
    assert f"'{option[0]}'" in result.output
    assert "cannot be combined" in result.output


def test_request_reserve_conflict() -> None:
    result = runner.invoke(app, _request_args("--recipe", "https://example.com/r.yaml", "--reserve"))

    assert result.exit_code == 255
    assert "'--reserve'" in result.output


def test_restart_keeps_recipe() -> None:
    result = _restart(_restart_args(), {"recipe": "https://example.com/r.yaml"})

    assert result.exit_code == 0, result.output
    assert _dry_run_json(result.output)["test"]["fmf"]["recipe"] == "https://example.com/r.yaml"


@pytest.mark.parametrize(
    ("option", "key"),
    [("--plan", "name"), ("--plan-filter", "plan_filter"), ("--test", "test_name"), ("--test-filter", "test_filter")],
)
def test_restart_selector_drops_recipe(option: str, key: str) -> None:
    result = _restart(_restart_args(option, "value"), {"recipe": "https://example.com/r.yaml"})

    assert result.exit_code == 0, result.output
    fmf = _dry_run_json(result.output)["test"]["fmf"]
    assert "recipe" not in fmf
    assert fmf[key] == "value"


def test_restart_replaces_recipe_and_drops_selectors(recipe_file: Path) -> None:
    stored = {"name": "/plan", "plan_filter": "tag:x", "test_name": "t", "test_filter": "tag:y"}

    result = _restart(_restart_args("--recipe", str(recipe_file)), stored)

    assert result.exit_code == 0, result.output
    fmf = _dry_run_json(result.output)["test"]["fmf"]
    assert gzip.decompress(base64.b64decode(fmf["recipe"])).decode() == RECIPE
    assert not set(stored) & set(fmf)


def test_restart_hidden_recipe() -> None:
    result = _restart(_restart_args(), {"recipe": "hidden"})

    assert result.exit_code == 255
    assert "hidden because you are not the owner" in result.output


def test_restart_hidden_recipe_replaced(recipe_file: Path) -> None:
    result = _restart(_restart_args("--recipe", str(recipe_file)), {"recipe": "hidden"})

    assert result.exit_code == 0, result.output
    fmf = _dry_run_json(result.output)["test"]["fmf"]
    assert gzip.decompress(base64.b64decode(fmf["recipe"])).decode() == RECIPE


def test_restart_recipe_conflict(recipe_file: Path) -> None:
    result = _restart(_restart_args("--recipe", str(recipe_file), "--plan", "p"), {})

    assert result.exit_code == 255
    assert "'--plan'" in result.output


def test_request_sanity_conflict() -> None:
    result = runner.invoke(app, _request_args("--recipe", "https://example.com/r.yaml", "--sanity"))

    assert result.exit_code == 255
    assert "'--sanity'" in result.output


def test_request_sti_conflict() -> None:
    result = runner.invoke(app, _request_args("--recipe", "https://example.com/r.yaml", "--test-type", "sti"))

    assert result.exit_code == 255
    assert "compatible only with 'tmt' tests" in result.output


def test_request_does_not_leak_recipe_between_calls() -> None:
    runner.invoke(app, _request_args("--recipe", "https://example.com/r.yaml"))
    result = runner.invoke(app, _request_args())

    assert result.exit_code == 0, result.output
    assert "recipe" not in _dry_run_json(result.output)["test"]["fmf"]


def test_unreadable_file(recipe_file: Path) -> None:
    with mock.patch("builtins.open", side_effect=PermissionError("denied")):
        result = runner.invoke(app, _request_args("--recipe", str(recipe_file)))

    assert result.exit_code == 255
    assert "Could not read recipe file" in result.output


def test_restart_reserve_with_recipe() -> None:
    result = _restart(_restart_args("--reserve"), {"recipe": "https://example.com/r.yaml"})

    assert result.exit_code == 255
    assert "'--reserve'" in result.output


def test_restart_reserve_with_replacing_recipe(recipe_file: Path) -> None:
    result = _restart(_restart_args("--reserve", "--recipe", str(recipe_file)), {})

    assert result.exit_code == 255
    assert "'--reserve'" in result.output


def test_restart_sti_recipe(recipe_file: Path) -> None:
    stored = _stored_request({})
    stored.get.return_value.json.return_value["test"] = {"sti": {"url": "https://example.com/repo", "ref": "main"}}

    with mock.patch("tft.cli.commands.requests.Session", return_value=stored):
        result = runner.invoke(app, _restart_args("--recipe", str(recipe_file)))

    assert result.exit_code == 255
    assert "compatible only with 'tmt' tests" in result.output
