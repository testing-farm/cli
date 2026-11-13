# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import sys
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest
import requests
import typer
from typer.testing import CliRunner

from tft.cli.commands import check_token
from tft.cli.tool import app

API_URL = 'https://api.test/'
COMPOSES = {'composes': [{'name': 'Fedora-41', 'type': 'compose'}]}

runner = CliRunner()


def _keyring(password: Optional[str]) -> mock.Mock:
    fake = mock.Mock()
    fake.get_password.return_value = password
    return fake


def _no_container() -> Any:
    # the result must not depend on whether the tests run inside the Testing Farm container
    return mock.patch('tft.cli.commands.os.path.exists', return_value=False)


def _response(payload: Dict[str, Any]) -> mock.Mock:
    response = mock.Mock(status_code=200)
    response.json.return_value = payload
    return response


def _env(token: Optional[str]) -> Dict[str, Optional[str]]:
    # `None` unsets the variable for the duration of the invocation
    return {'TESTING_FARM_API_URL': API_URL, 'TESTING_FARM_API_TOKEN': token}


def test_check_token_returns_given_token_without_keyring() -> None:
    fake = _keyring('keyring-token')

    with _no_container(), mock.patch.dict(sys.modules, {'keyring': fake}):
        assert check_token(API_URL, 'env-token') == 'env-token'

    fake.get_password.assert_not_called()


def test_check_token_falls_back_to_keyring() -> None:
    fake = _keyring('keyring-token')

    with _no_container(), mock.patch.dict(sys.modules, {'keyring': fake}):
        assert check_token(API_URL, None) == 'keyring-token'

    fake.get_password.assert_called_once_with(API_URL, 'api-token')


def test_check_token_without_token_exits_with_hint(capsys: pytest.CaptureFixture) -> None:
    with _no_container(), mock.patch.dict(sys.modules, {'keyring': _keyring(None)}):
        with pytest.raises(typer.Exit) as exc:
            check_token(API_URL, None, hint='Or use `--ranch` to list composes without a token.')

    assert exc.value.exit_code == 255
    out = capsys.readouterr().out
    assert 'No API token found' in out
    assert '--ranch' in out


def test_check_token_without_token_exits_without_hint(capsys: pytest.CaptureFixture) -> None:
    with _no_container(), mock.patch.dict(sys.modules, {'keyring': _keyring(None)}):
        with pytest.raises(typer.Exit):
            check_token(API_URL, None)

    out = capsys.readouterr().out
    assert 'No API token found' in out
    assert '--ranch' not in out


def test_composes_without_ranch_and_token_requires_ranch() -> None:
    with _no_container(), mock.patch.dict(sys.modules, {'keyring': _keyring(None)}), mock.patch.object(
        requests.Session, 'get'
    ) as mock_get:
        result = runner.invoke(app, ['composes'], env=_env(None))

    assert result.exit_code == 255
    assert '--ranch' in result.output
    mock_get.assert_not_called()


def test_composes_with_ranch_does_not_check_token() -> None:
    with mock.patch('tft.cli.command.composes.check_token') as mock_check, mock.patch.object(
        requests.Session, 'get', return_value=_response(COMPOSES)
    ) as mock_get:
        result = runner.invoke(app, ['composes', '--ranch', 'public'], env=_env(None))

    assert result.exit_code == 0, result.output
    assert 'Fedora-41' in result.output
    mock_check.assert_not_called()
    mock_get.assert_called_once_with('https://api.test/v0.2/composes/public')


def test_composes_without_ranch_uses_keyring_token_and_whoami_ranch() -> None:
    fake = _keyring('keyring-token')
    responses: List[mock.Mock] = [_response({'token': {'ranch': 'redhat'}}), _response(COMPOSES)]

    with _no_container(), mock.patch.dict(sys.modules, {'keyring': fake}), mock.patch.object(
        requests.Session, 'get', side_effect=responses
    ) as mock_get:
        result = runner.invoke(app, ['composes'], env=_env(None))

    assert result.exit_code == 0, result.output
    fake.get_password.assert_called_once_with(API_URL, 'api-token')
    assert mock_get.call_args_list == [
        mock.call('https://api.test/v0.1/whoami', headers={'Authorization': 'Bearer keyring-token'}),
        mock.call('https://api.test/v0.2/composes/redhat'),
    ]
