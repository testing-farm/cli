# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import glob
import os
import subprocess
import sys
import uuid
from typing import Any, Dict, List, NoReturn, Optional, Union

import requests
import requests.adapters
import typer
from rich.console import Console
from ruamel.yaml import YAML
from urllib3 import Retry

from tft.cli.config import settings

console = Console(soft_wrap=True)
console_stderr = Console(soft_wrap=True, file=sys.stderr)


def exit_error(error: str) -> NoReturn:
    """Exit with given error message"""
    console.print(f"⛔ {error}", style="red")
    raise typer.Exit(code=255)


def cmd_output_or_exit(command: str, error: str) -> str:
    """Return local command output or exit with given error message"""
    try:
        output = subprocess.check_output(command.split(), stderr=subprocess.STDOUT)

    except subprocess.CalledProcessError:
        exit_error(error)

    return output.rstrip().decode("utf-8")


def artifacts(type: str, artifacts_raw: List[str]) -> List[Dict[str, str]]:
    """Return artifacts List for given artifact type"""
    artifacts = []

    for artifact in artifacts_raw:
        if '=' in artifact:
            artifact_dict = options_to_dict('artifact `{}`'.format(artifact), normalize_multistring_option([artifact]))
        else:
            artifact_dict = {'id': artifact}

        if 'install' in artifact_dict:
            artifact_dict['install'] = normalize_bool_option(artifact_dict['install'])  # pyre-ignore[6]

        artifacts.append({'type': type, **artifact_dict})

    return artifacts


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


def options_from_file(filepath) -> Dict[str, str]:
    """Read environment variables from a yaml file."""

    with open(filepath, 'r') as file:
        try:
            yaml = YAML(typ="safe").load(file.read())
        except Exception:
            exit_error(f"Failed to load variables from yaml file {filepath}.")

        if not yaml:  # pyre-ignore[61]  # pyre ignores NoReturn in exit_error
            return {}

        if not isinstance(yaml, dict):  # pyre-ignore[61]  # pyre ignores NoReturn in exit_error
            exit_error(f"Environment file {filepath} is not a dict.")

        if any([isinstance(value, (list, dict)) for value in yaml.values()]):
            exit_error(f"Values of environment file {filepath} are not primitive types.")

        return yaml  # pyre-ignore[61]  # pyre ignores NoReturn in exit_error


def options_to_dict(name: str, options: List[str]) -> Dict[str, str]:
    """Create a dictionary from list of `key=value|@file` options"""

    options_dict = {}
    for option in options:
        # Option is `@file`
        if option.startswith('@'):
            if not os.path.isfile(option[1:]):
                exit_error(f"Invalid environment file in option `{option}` specified.")
            options_dict.update(options_from_file(option[1:]))

        # Option is `key=value`
        else:
            try:
                options_dict.update({option.split("=", 1)[0]: option.split("=", 1)[1]})
            except IndexError:
                exit_error(f"Option `{option}` is invalid, must be defined as `key=value|@file`.")

    return options_dict


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
    retry_backoff_factor: float = settings.DEFAULT_RETRY_BACKOFF_FACTOR,
    status_forcelist_extend: Optional[List[int]] = None,
) -> None:
    # urllib3 1.26.0 deprecated method_whitelist, and 2.0.0 removed it:
    #  - https://github.com/urllib3/urllib3/commit/382ab32f23795c44faae83b4e8b18a16fb605a0a
    #  - https://github.com/urllib3/urllib3/commit/c67c0949e9c91c7621ea718a7f297ecac7c3b79e
    if hasattr(Retry, "DEFAULT_ALLOWED_METHODS"):
        allowed_retry_parameter = "allowed_methods"
    else:
        allowed_retry_parameter = "method_whitelist"

    status_forcelist_extend = status_forcelist_extend or []

    params = {
        "total": retries,
        "status_forcelist": [
            429,  # Too Many Requests
            500,  # Internal Server Error
            502,  # Bad Gateway
            503,  # Service Unavailable
            504,  # Gateway Timeout
        ]
        + status_forcelist_extend,
        allowed_retry_parameter: ['HEAD', 'GET', 'POST', 'DELETE', 'PUT'],
        "backoff_factor": retry_backoff_factor,
    }
    retry_strategy = Retry(**params)

    timeout_adapter = TimeoutHTTPAdapter(timeout=timeout, max_retries=retry_strategy)

    session.mount('https://', timeout_adapter)
    session.mount('http://', timeout_adapter)


def normalize_multistring_option(options: List[str], separator: str = ',') -> List[str]:
    return sum([[option.strip() for option in item.split(separator)] for item in options], [])


def normalize_bool_option(option_value: Union[str, bool]) -> bool:
    if str(option_value).strip().lower() in ('yes', 'true', '1', 'y', 'on'):
        return True
    return False


def read_glob_paths(glob_paths: List[str]) -> str:
    paths = [path for glob_path in glob_paths for path in glob.glob(os.path.expanduser(glob_path))]

    contents: List[str] = []

    for path in paths:
        if not os.path.isfile(path) or not os.access(path, os.R_OK):
            exit_error(f"Error reading '{path}'.")
        with open(path, 'r') as file:
            contents.append(file.read())

    return ''.join(contents)
