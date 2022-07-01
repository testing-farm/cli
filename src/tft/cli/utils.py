# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import subprocess
import uuid
from typing import Any, Dict, List

import typer


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

        container[path_splitted.pop()] = value

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
