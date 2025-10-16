# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import io
import json
import re
import urllib.parse
from typing import Any, List, Optional

import requests
import typer
from rich.progress import Progress, SpinnerColumn
from rich.syntax import Syntax
from rich.table import Table  # type: ignore
from ruamel.yaml import YAML  # type: ignore

from tft.cli.commands import ARGUMENT_API_TOKEN, ARGUMENT_API_URL
from tft.cli.config import settings
from tft.cli.utils import (
    OutputFormat,
    StrEnum,
    authorization_headers,
    check_unexpected_arguments,
    console,
    exit_error,
    handle_response_errors,
    install_http_retries,
)


class Ranch(StrEnum):
    public = "public"
    redhat = "redhat"


def render_text(composes_json: Any, show_regex: bool) -> None:
    """
    Show list of composes as a text.
    """

    lines: list[str] = []

    for compose in sorted(composes_json, key=lambda compose: compose["name"]):
        text = f"{compose['name']}"

        if show_regex:
            if compose["type"] == "regex":
                text += " [bold][green]regex[/green][/bold]"
            else:
                text += " [bold][green]compose[/green][/bold]"

        lines.append(text)

    console.print("\n".join(lines))


def render_table(composes_json: Any, show_regex: bool) -> None:
    """
    Show list of composes as a table.
    """
    table = Table(show_header=True, header_style="bold magenta")

    table.add_column("name", justify="left")

    if show_regex:
        table.add_column("type", justify="left")

    for compose in sorted(composes_json, key=lambda compose: compose["name"]):
        row = [compose["name"]]

        if show_regex:
            row.append(compose["type"])

        table.add_row(*row)

    console.print(table)


def composes(
    context: typer.Context,
    api_token: str = ARGUMENT_API_TOKEN,
    api_url: str = ARGUMENT_API_URL,
    ranch: Optional[Ranch] = typer.Option(
        None, help="List composes for this ranch, instead of the ranch of your token."
    ),
    search: Optional[str] = typer.Option(
        None,
        "-s",
        "--search",
        help="Search for composes based on the given regular expression. For searching `re.search` is used.",
    ),
    show_regex: bool = typer.Option(
        False,
        help="Show also regular expressions used to accept additional composes.",
    ),
    validate: Optional[List[str]] = typer.Option(
        None,
        "-v",
        "--validate",
        help="Verify that given compose would be accepted by Testing Farm. Can be specified multiple times.",
    ),
    format: OutputFormat = typer.Option(
        "text", help=f"Output format to use. Possible formats: {OutputFormat.available_formats()}"
    ),
):
    """
    List composes accepted by Testing Farm.

    When Testing Farm token is provided, the command uses the ranch corresponding to your token.
    To force listing of composes for a specific ranch, use the `--ranch` option.
    """

    # Accept these arguments only via environment variables
    check_unexpected_arguments(context, "api_url", "api_token")

    # Setting up HTTP retries
    session = requests.Session()
    install_http_retries(session)

    # check for token
    if not api_token and not ranch:
        exit_error("No API token found and no ranch specified. Cannot determine ranch.")

    # Validate token if provided
    if api_token and not ranch:
        whoami_url = urllib.parse.urljoin(api_url, "v0.1/whoami")
        try:
            with Progress(SpinnerColumn(), transient=True) as progress:
                progress.add_task(description="")

                response = session.get(whoami_url, headers=authorization_headers(api_token))
                handle_response_errors(response)

                ranch = response.json()['token']['ranch']

        except requests.RequestException as e:
            exit_error(f"Failed to validate token: {e}")

    # Compile the search regular expression
    search_pattern = re.compile(search) if search else None

    # Fetch composes
    with Progress(SpinnerColumn(), transient=True) as progress:
        progress.add_task(description="")

        composes_url = urllib.parse.urljoin(api_url, f"v0.2/composes/{ranch}")

        response = session.get(composes_url)
        handle_response_errors(response)

        composes_json = response.json().get("composes") or []

        if not composes_json:
            exit_error(f"No composes found in Testing Farm. Please file an issue to {settings.ISSUE_TRACKER}")

    if search_pattern:
        composes_json = [compose for compose in composes_json if search_pattern.search(compose["name"])]

        if not composes_json:
            exit_error(f"No composes found for '{search_pattern.pattern}'.")

    if validate:

        def _compose_accepted(compose: str):
            console.print(f"✅ Compose '{compose}' is valid")

        for validated_compose in validate:
            for compose in composes_json:
                if compose["type"] == "compose" and validated_compose == compose["name"]:
                    _compose_accepted(validated_compose)
                    break

                if compose["type"] == "regex" and re.match(compose["name"], validated_compose):
                    _compose_accepted(validated_compose)
                    break
            else:
                console.print(f"❌ Compose '{validated_compose}' is invalid")

        return

    if not show_regex:
        composes_json = [compose for compose in composes_json if compose["type"] != "regex"]

    if format == OutputFormat.json:
        json_dump = json.dumps(composes_json) or '[]'
        console.print_json(json_dump)
        return

    if format == OutputFormat.yaml:
        yaml_dump = io.StringIO()
        YAML().dump(composes_json, yaml_dump)
        syntax = Syntax(yaml_dump.getvalue(), "yaml")
        console.print(syntax)
        return

    if format == OutputFormat.table:
        render_table(composes_json, show_regex)
        return

    render_text(composes_json, show_regex)
