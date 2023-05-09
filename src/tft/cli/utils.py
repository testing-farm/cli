# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import subprocess
import uuid
from typing import Any, Dict, List, Union

import requests
import requests.adapters
import typer
from urllib3 import Retry

from tft.cli.config import settings


def exit_error(error: str):
    """Exit with given error message"""
    typer.secho(f"⛔ {error}", fg=typer.colors.RED)
    raise typer.Exit(code=255)


def cmd_output_or_exit(command: str, error: str) -> str:
    """Return local command output or exit with given error message"""
    try:
        output = subprocess.check_output(command.split(), stderr=subprocess.STDOUT)

    except subprocess.CalledProcessError:
        exit_error(error)

    return output.rstrip().decode("utf-8")


def artifacts(type: str, ids: List[str]) -> List[Dict[str, str]]:
    """Return artifacts List for given artifact type"""
    return [{"type": type, "id": id} for id in ids]


def blue(message: str) -> str:
    """Colorize text to bright blue color"""
    return typer.style(f"{message}", fg=typer.colors.BRIGHT_BLUE)


def hw_constraints(hardware: List[str]) -> Dict[Any, Any]:
    """Convert hardware parameters to a dictionary"""

    constraints: Dict[Any, Any] = {}

    for raw_constraint in hardware:
        path, value = raw_constraint.split('=', 1)

        if not path or not value:
            exit_error(f"cannot parse hardware constraint `{raw_constraint}`")

        # Walk the path, step by step, and initialize containers along the way. The last step is not
        # a name of another nested container, but actually a name in the last container.
        container: Any = constraints
        path_splitted = path.split('.')

        while len(path_splitted) > 1:
            step = path_splitted.pop(0)

            if step not in container:
                container[step] = {}

            container = container[step]

        value_mixed: Union[bool, str] = value

        if value.lower() in ['true']:
            value_mixed = True

        elif value.lower() in ['false']:
            value_mixed = False

        container[path_splitted.pop()] = value_mixed

    # automatically convert disk and network values to a list, as the standard requires
    return {key: value if key not in ("disk", "network") else [value] for key, value in constraints.items()}


def options_to_dict(name: str, options: List[str]) -> Dict[str, str]:
    """Create a dictionary from list of `key=value` options"""
    try:
        return {option.split("=", 1)[0]: option.split("=", 1)[1] for option in options}

    except IndexError:
        exit_error(f"Options for {name} are invalid, must be defined as `key=value`")

    return {}


def uuid_valid(value: str, version: int = 4) -> bool:
    """
    Validates that given `value` is a valid UUID version 4.
    """
    try:
        uuid.UUID(value, version=version)
        return True
    except ValueError:
        return False


class TimeoutHTTPAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.timeout = kwargs.pop('timeout', settings.DEFAULT_API_TIMEOUT)

        super().__init__(*args, **kwargs)

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:  # type: ignore[override]
        kwargs.setdefault('timeout', self.timeout)

        return super().send(request, **kwargs)


def install_http_retries(
    session: requests.Session,
    timeout: int = settings.DEFAULT_API_TIMEOUT,
    retries: int = settings.DEFAULT_API_RETRIES,
    retry_backoff_factor: int = settings.DEFAULT_RETRY_BACKOFF_FACTOR,
) -> None:
    # urllib3 1.26.0 deprecated method_whitelist, and 2.0.0 removed it:
    #  - https://github.com/urllib3/urllib3/commit/382ab32f23795c44faae83b4e8b18a16fb605a0a
    #  - https://github.com/urllib3/urllib3/commit/c67c0949e9c91c7621ea718a7f297ecac7c3b79e
    if hasattr(Retry, "DEFAULT_ALLOWED_METHODS"):
        allowed_retry_parameter = "allowed_methods"
    else:
        allowed_retry_parameter = "method_whitelist"

    params = {
        "total": retries,
        "status_forcelist": [
            429,  # Too Many Requests
            500,  # Internal Server Error
            502,  # Bad Gateway
            503,  # Service Unavailable
            504,  # Gateway Timeout
        ],
        allowed_retry_parameter: ['HEAD', 'GET', 'POST', 'DELETE', 'PUT'],
        "backoff_factor": retry_backoff_factor,
    }
    retry_strategy = Retry(**params)

    timeout_adapter = TimeoutHTTPAdapter(timeout=timeout, max_retries=retry_strategy)

    session.mount('https://', timeout_adapter)
    session.mount('http://', timeout_adapter)


def normalize_multistring_option(options: List[str], separator: str = ',') -> List[str]:
    return sum([[option.strip() for option in item.split(separator)] for item in options], [])
