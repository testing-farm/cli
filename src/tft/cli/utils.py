# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import glob
import itertools
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, NoReturn, Optional, Union

import pendulum
import requests
import requests.adapters
import typer
from click.core import ParameterSource
from dotenv import dotenv_values
from rich.console import Console
from ruamel.yaml import YAML  # type: ignore
from urllib3 import Retry

from tft.cli.config import settings

console = Console(soft_wrap=True)
console_stderr = Console(soft_wrap=True, file=sys.stderr)


@dataclass
class Age:
    value: int
    unit: str

    _unit_multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    _unit_human = {"s": "second", "m": "minute", "h": "hour", "d": "day"}

    @classmethod
    def from_string(cls, age_string: str) -> 'Age':
        value, unit = age_string[:-1], age_string[-1]
        if unit not in cls._unit_multiplier:
            raise typer.BadParameter(f"Age must end with {', '.join(cls._unit_multiplier.keys())}")

        if not value.isdigit():
            raise typer.BadParameter(f"Invalid age value {value}")

        return cls(value=int(age_string[:-1]), unit=age_string[-1])

    @property
    def birth_date(self) -> pendulum.DateTime:
        now = pendulum.now(tz="UTC")
        return now - pendulum.duration(seconds=self.value * self._unit_multiplier[self.unit])

    @property
    def human(self) -> str:
        return f"{self.value} {self._unit_human[self.unit]}{'s' if self.value > 1 else ''}"

    @staticmethod
    def available_units() -> str:
        return "s (seconds), m (minutes), h (hours) or d (days)"

    def to_string(self, format="%Y-%m-%dT%H:%M:%S") -> str:
        return self.birth_date.strftime(format)

    def __str__(self):
        return f"{self.value}{self.unit}"


class OutputFormat(str, Enum):
    text = "text"
    json = "json"
    yaml = "yaml"
    table = "table"

    @staticmethod
    def available_formats():
        return "text, json or table"


def exit_error(error: str) -> NoReturn:
    """Exit with given error message"""
    console.print(f"⛔ {error}", style="red")
    raise typer.Exit(code=255)


def handle_401_response(response: requests.Response) -> NoReturn:
    """Handle 401 Unauthorized responses with appropriate error message.

    Differentiates between expired tokens and invalid tokens based on
    the API response message.
    """
    try:
        error_msg = response.json().get('message', '')
        if error_msg == "Token has expired":
            exit_error(
                f"API token has expired. Please generate a new token at "
                f"{settings.ONBOARDING_DOCS} and update your TESTING_FARM_API_TOKEN."
            )
    except requests.exceptions.JSONDecodeError:
        pass
    exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")


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

        path_splitted = path.split('.')
        first_key = path_splitted[0]

        # Special handling for network and disk as they are lists
        if first_key in ("network", "disk"):
            if first_key not in constraints:
                constraints[first_key] = []

            if len(path_splitted) > 1:
                new_dict = {}
                current = new_dict
                # Handle all nested levels except the last one
                for key in path_splitted[1:-1]:
                    current[key] = {}
                    current = current[key]
                # Set the final value
                current[path_splitted[-1]] = value
                constraints[first_key].append(new_dict)
            continue

        # Special handling for CPU flags as they are also a list
        if first_key == 'cpu' and len(path_splitted) == 2 and path_splitted[1] == 'flag':
            second_key = 'flag'

            if first_key not in constraints:
                constraints[first_key] = {}

            if second_key not in constraints[first_key]:
                constraints[first_key][second_key] = []

            constraints[first_key][second_key].append(value)

            continue

        # Walk the path, step by step, and initialize containers along the way. The last step is not
        # a name of another nested container, but actually a name in the last container.
        container: Any = constraints

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

        final_key = path_splitted.pop()

        # Handle compatible.distro as a list
        if final_key == 'distro':
            if final_key not in container:
                container[final_key] = []
            container[final_key].append(value_mixed)
        else:
            container[final_key] = value_mixed

    return constraints


def options_from_yaml(filepath: str) -> Optional[Dict[str, Optional[str]]]:
    """Read environment variables from yaml content.

    Raises:
        ValueError: If the file cannot be parsed as YAML or has invalid structure.
    """

    with open(filepath, 'r') as file:
        content = file.read()

    try:
        yaml = YAML(typ="safe").load(content)
    except Exception:
        return None

    if not yaml:
        return {}

    if not isinstance(yaml, dict):
        exit_error(f"Environment file {filepath} is not a dict.")

    if any([isinstance(value, (list, dict)) for value in yaml.values()]):
        exit_error(f"Values of environment file {filepath} are not primitive types.")

    return yaml


def options_from_dotenv(filepath: str) -> Dict[str, Optional[str]]:
    """Read environment variables from dotenv file.

    Raises:
        Exception: If the file cannot be parsed as dotenv.
    """
    try:
        return dotenv_values(filepath)
    except Exception:
        exit_error(f"Failed to load variables from file {filepath}.")


def options_from_file(filepath) -> Dict[str, Optional[str]]:
    """Read environment variables from a yaml or dotenv file."""
    # Try to load from yaml first
    # If that fails, try to load from dotenv
    yaml = options_from_yaml(filepath)

    if yaml is None:
        return options_from_dotenv(filepath)

    return yaml


def options_to_dict(name: str, options: List[str]) -> Dict[str, str]:
    """Create a dictionary from list of `key=value|@file` options"""

    options_dict = {}

    # Turn option list such as
    # `['aaa=bbb "foo foo=bar bar"', 'foo=bar']` into
    # `['aaa=bbb', 'foo foo=bar bar', 'foo=bar']`
    options = list(itertools.chain.from_iterable(shlex.split(option) for option in options))

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


def extract_uuid(value: str) -> str:
    """
    Extracts a UUID from a string. If the string is already a valid UUID, returns it.
    If the string contains a UUID, extracts and returns it.
    Raises typer.Exit with error message if no valid UUID is found.
    """
    # Check if the value is already a valid UUID
    if uuid_valid(value):
        return value

    # UUID pattern for extracting UUIDs from strings
    uuid_pattern = re.compile('[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')

    # Try to extract UUID from string
    uuid_match = uuid_pattern.search(value)
    if uuid_match:
        return uuid_match.group()

    exit_error(f"Could not find a valid Testing Farm request id in '{value}'.")


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

    from typing import Any, Dict

    params: Dict[str, Any] = {
        "total": retries,
        "status_forcelist": [
            429,  # Too Many Requests
            500,  # Internal Server Error
            502,  # Bad Gateway
            503,  # Service Unavailable
            504,  # Gateway Timeout
        ]
        + status_forcelist_extend,
        "backoff_factor": retry_backoff_factor,
    }
    params[allowed_retry_parameter] = ['HEAD', 'GET', 'POST', 'DELETE', 'PUT']
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


def check_unexpected_arguments(context: typer.Context, *args: str) -> Union[None, NoReturn]:
    for argument in args:
        if context.get_parameter_source(argument) == ParameterSource.COMMANDLINE:
            exit_error(
                f"Unexpected argument '{context.params.get(argument)}'. "
                "Please make sure you are passing the parameters correctly."
            )


def validate_age(value: str) -> Age:
    if value.endswith("m"):
        return Age(int(value[:-1]), "m")
    elif value.endswith("d"):
        return Age(int(value[:-1]), "d")
    else:
        raise ValueError("Age must end with 'm' for months or 'd' for days.")


def authorization_headers(api_key: str) -> Dict[str, str]:
    """
    Return a dict with headers for a request to Testing Farm API.
    Used for authentication.
    """
    return {'Authorization': f'Bearer {api_key}'}


def edit_with_editor(data: Any, description: Optional[str]) -> Any:
    """
    Open data in an editor for user modification and return it back.
    If description specified, print it as a user message together with the used editor.
    """
    # Get the editor from environment variable, fallback to sensible defaults
    editor = os.environ.get('EDITOR')
    if not editor:
        # Try common editors in order of preference
        for candidate in ['vim', 'vi', 'nano', 'emacs']:
            if shutil.which(candidate):
                editor = candidate
                break

    if not editor:
        exit_error("No editor found. Please set the 'EDITOR' environment variable.")

    # Create a temporary file with the JSON content
    with tempfile.NamedTemporaryFile(mode='w') as temp_file:
        temp_file.write(data)
        temp_file.flush()

        # Open the editor
        if description:
            console.print(f"✏️  {description}, editor '{editor}'")
        result = subprocess.run([editor, temp_file.name])

        if result.returncode != 0:
            exit_error(f"Editor '{editor}' exited with non-zero status: {result.returncode}")

        # Read the modified content
        with open(temp_file.name, 'r') as modified_file:
            return modified_file.read()
