# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import subprocess
import uuid
from typing import Dict, List, Optional

import typer


def exit_error(error: str):
    """Exit with given error message"""
    typer.secho(f"⛔ {error}", fg=typer.colors.RED)
    raise typer.Exit(code=255)


def cmd_output_or_exit(command: str, error: str) -> Optional[str]:
    """Return local command output or exit with given error message"""
    try:
        output = subprocess.check_output(command.split(), stderr=subprocess.STDOUT)
        return output.rstrip().decode("utf-8")

    except subprocess.CalledProcessError:
        exit_error(error)

    return None


def blue(message: str) -> str:
    """Colorize text to bright blue color"""
    return typer.style(f"{message}", fg=typer.colors.BRIGHT_BLUE)


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
