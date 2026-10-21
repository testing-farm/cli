# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

from typing import Optional
from unittest import mock

import pytest
import requests
import requests.adapters

from tft.cli.utils import TimeoutHTTPAdapter, install_http_retries


def _prepared_request(method: str = 'GET') -> requests.PreparedRequest:
    return requests.Request(method=method, url='https://example.com').prepare()


class _Response:
    """Stand-in for `requests.Response` whose `.content` either raises or returns a value."""

    def __init__(self, exc: Optional[Exception] = None) -> None:
        self._exc = exc

    @property
    def content(self) -> bytes:
        if self._exc:
            raise self._exc
        return b'ok'


def test_body_read_retries_on_chunked_encoding_error() -> None:
    request = _prepared_request()
    adapter = TimeoutHTTPAdapter(body_read_retries=2, body_read_retry_backoff_factor=0)

    responses = [
        _Response(requests.exceptions.ChunkedEncodingError('broken')),
        _Response(),
    ]

    with mock.patch.object(requests.adapters.HTTPAdapter, 'send', side_effect=responses) as mock_send, mock.patch(
        'tft.cli.utils.time.sleep'
    ) as mock_sleep:
        response = adapter.send(request)

    assert response is responses[1]
    assert mock_send.call_count == 2
    mock_sleep.assert_called_once_with(0)


def test_body_read_retries_on_connection_error() -> None:
    request = _prepared_request()
    adapter = TimeoutHTTPAdapter(body_read_retries=2, body_read_retry_backoff_factor=0)

    responses = [
        _Response(requests.exceptions.ConnectionError('Read timed out.')),
        _Response(),
    ]

    with mock.patch.object(requests.adapters.HTTPAdapter, 'send', side_effect=responses) as mock_send, mock.patch(
        'tft.cli.utils.time.sleep'
    ):
        response = adapter.send(request)

    assert response is responses[1]
    assert mock_send.call_count == 2


def test_body_read_ssl_error_is_not_retried() -> None:
    request = _prepared_request()
    adapter = TimeoutHTTPAdapter(body_read_retries=5, body_read_retry_backoff_factor=0)

    responses = [_Response(requests.exceptions.SSLError('certificate verify failed'))]

    with mock.patch.object(requests.adapters.HTTPAdapter, 'send', side_effect=responses) as mock_send, mock.patch(
        'tft.cli.utils.time.sleep'
    ) as mock_sleep:
        with pytest.raises(requests.exceptions.SSLError):
            adapter.send(request)

    # only the first attempt is made, the SSL error is fatal and not retried
    assert mock_send.call_count == 1
    mock_sleep.assert_not_called()


def test_body_read_retries_exhausted_raises() -> None:
    request = _prepared_request()
    adapter = TimeoutHTTPAdapter(body_read_retries=2, body_read_retry_backoff_factor=0)

    exc = requests.exceptions.ConnectionError('Read timed out.')
    responses = [_Response(exc), _Response(exc), _Response(exc)]

    with mock.patch.object(requests.adapters.HTTPAdapter, 'send', side_effect=responses) as mock_send, mock.patch(
        'tft.cli.utils.time.sleep'
    ):
        with pytest.raises(requests.exceptions.ConnectionError):
            adapter.send(request)

    # the initial attempt plus the two retries, then give up
    assert mock_send.call_count == 3


def test_body_read_retry_backoff_sleep_values() -> None:
    request = _prepared_request()
    adapter = TimeoutHTTPAdapter(body_read_retries=3, body_read_retry_backoff_factor=2)

    exc = requests.exceptions.ConnectionError('Read timed out.')
    responses = [_Response(exc), _Response(exc), _Response()]

    with mock.patch.object(requests.adapters.HTTPAdapter, 'send', side_effect=responses), mock.patch(
        'tft.cli.utils.time.sleep'
    ) as mock_sleep:
        adapter.send(request)

    # backoff_factor * 2 ** attempt for attempts 0 and 1: 2 * 2**0 = 2, 2 * 2**1 = 4
    assert mock_sleep.call_args_list == [mock.call(2), mock.call(4)]


def test_body_read_retry_backoff_is_capped() -> None:
    request = _prepared_request()
    adapter = TimeoutHTTPAdapter(body_read_retries=1, body_read_retry_backoff_factor=1000)

    exc = requests.exceptions.ConnectionError('Read timed out.')
    responses = [_Response(exc), _Response()]

    with mock.patch.object(requests.adapters.HTTPAdapter, 'send', side_effect=responses), mock.patch(
        'tft.cli.utils.time.sleep'
    ) as mock_sleep:
        adapter.send(request)

    mock_sleep.assert_called_once_with(120)


def test_body_read_retries_not_applied_to_unsafe_methods() -> None:
    request = _prepared_request(method='POST')
    adapter = TimeoutHTTPAdapter(body_read_retries=2, body_read_retry_backoff_factor=0)

    response = _Response()

    with mock.patch.object(requests.adapters.HTTPAdapter, 'send', return_value=response) as mock_send:
        assert adapter.send(request) is response

    mock_send.assert_called_once()


def test_body_read_retries_not_applied_to_streaming_responses() -> None:
    request = _prepared_request()
    adapter = TimeoutHTTPAdapter(body_read_retries=2, body_read_retry_backoff_factor=0)

    response = _Response()

    with mock.patch.object(requests.adapters.HTTPAdapter, 'send', return_value=response) as mock_send:
        assert adapter.send(request, stream=True) is response

    mock_send.assert_called_once()


def test_install_http_retries_passes_retries_and_backoff_to_adapter() -> None:
    session = requests.Session()

    install_http_retries(session, retries=7, retry_backoff_factor=3.5)

    adapter = session.get_adapter('https://example.com')
    assert isinstance(adapter, TimeoutHTTPAdapter)
    assert adapter.body_read_retries == 7
    assert adapter.body_read_retry_backoff_factor == 3.5
