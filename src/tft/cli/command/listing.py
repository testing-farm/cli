# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import io
import json
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Any, List, Optional, Tuple

import pendulum
import requests
import typer
from click.core import ParameterSource
from rich.progress import Progress, SpinnerColumn
from rich.syntax import Syntax
from rich.table import Table  # type: ignore
from ruamel.yaml import YAML  # type: ignore

from tft.cli.commands import (
    ARGUMENT_API_TOKEN,
    ARGUMENT_API_URL,
    ARGUMENT_INTERNAL_API_URL,
    PipelineState,
)
from tft.cli.config import settings
from tft.cli.utils import (
    Age,
    OutputFormat,
    authorization_headers,
    check_unexpected_arguments,
    console,
    exit_error,
    extract_uuid,
    install_http_retries,
    uuid_valid,
)

# Maximum lenght of compose which is still shown in table listing
MAX_COMPOSE_LENGTH = 30


class Ranch(str, Enum):
    public = "public"
    redhat = "redhat"


def get_artifacts_url(request):
    """
    Extract artifacts URL from request.
    """
    return (request.get('run', {}) or {}).get('artifacts', '<unavailable>')


def get_ranch(artifacts_url):
    """
    Deduce ranch according to artifacts url.
    """
    if 'unavailable' in artifacts_url:
        return '<unknown>'

    if 'redhat.com' in artifacts_url:
        return 'redhat'

    if 'testing-farm.io' in artifacts_url:
        return 'public'

    return '<unrecognized ranch>'


def get_ranch_colored(artifacts_url):
    """
    Deduce ranch according to artifacts url and return with color formatting.
    """
    ranch = get_ranch(artifacts_url)

    if ranch == 'redhat':
        return '[red]redhat[/red]'
    elif ranch == 'public':
        return '[blue]public[/blue]'
    else:
        return ranch


def calculate_started_time(request):
    """
    Calculate started time as: created + queued_time
    Returns None if calculation cannot be performed (missing data)
    """
    try:
        created_str = request.get('created')
        queued_time = request.get('queued_time')

        if not created_str or queued_time is None:
            return None

        # Parse created datetime
        created_dt = pendulum.parse(created_str, tz="UTC")

        # Add queued_time (in seconds)
        started_dt = created_dt.add(seconds=float(queued_time))

        return started_dt

    except (ValueError, TypeError, AttributeError):
        return None


def calculate_finished_time(request):
    """
    Calculate finished time as: created + queued_time + run_time
    Returns None if calculation cannot be performed (missing data or request not finished)
    """
    try:
        # Only calculate for completed requests
        if request.get('state') not in ['complete', 'error', 'canceled']:
            return None

        created_str = request.get('created')
        queued_time = request.get('queued_time')
        run_time = request.get('run_time')

        if not created_str or queued_time is None or run_time is None:
            return None

        # Parse created datetime
        created_dt = pendulum.parse(created_str, tz="UTC")

        # Add queued_time and run_time (both in seconds)
        total_seconds = float(queued_time) + float(run_time)
        finished_dt = created_dt.add(seconds=total_seconds)

        return finished_dt

    except (ValueError, TypeError, AttributeError):
        return None


def render_reservation_table(requests_json: Any, show_utc: bool) -> None:
    """Show list of reservation requests as a special table."""
    table = Table(show_header=True, header_style="bold magenta", expand=True)

    for column in ["state", "id", "ranch", "env", "user@ip", "started"]:
        table.add_column(column, justify="left" if column in ["env", "user@ip", "id"] else "center")

    def extract_guest_ip(request):
        """Extract guest IP from pipeline log."""
        artifacts_url = get_artifacts_url(request)
        if artifacts_url == '<unavailable>':
            return request, "<not-yet-available>"

        try:
            import requests

            session = requests.Session()
            pipeline_log = session.get(f"{artifacts_url}/pipeline.log").text
            guests = re.findall(r'Guest is ready.*root@([\d\w\.-]+)', pipeline_log)
            return request, f"root@{guests[0]}" if guests else "<not-yet-available>"
        except:  # noqa: E722
            return request, "<not-yet-available>"

    # Filter only active reservation requests (new, queued, running)
    reservation_requests = []
    for request in requests_json:
        # Only include active states
        if request.get('state') not in ['new', 'queued', 'running']:
            continue
        # Check if this is a reservation request by looking for reservation indicators
        environments = request.get('environments_requested', [])
        for env in environments:
            variables = env.get('variables') or {}
            if 'TF_RESERVATION_DURATION' in variables:
                reservation_requests.append(request)
                break

    if not reservation_requests:
        console.print("No active reservations found")
        return

    # Sort reservations
    sorted_requests = sorted(reservation_requests, key=lambda request: request['created'], reverse=True)

    # Extract IPs in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        ip_results = list(executor.map(extract_guest_ip, sorted_requests))

    # Create IP lookup map
    ip_map = {req['id']: ip for req, ip in ip_results}

    for request in sorted_requests:
        artifacts_url = get_artifacts_url(request)
        ranch = get_ranch_colored(artifacts_url)

        # Get environment info
        envs = []
        for environment in request['environments_requested']:
            arch = environment['arch']
            os_info = environment.get('os') or {}
            os_compose = os_info.get('compose')
            if os_compose:
                if len(os_compose) > MAX_COMPOSE_LENGTH:
                    envs.append(f"{arch:>7} (<too-long>)")
                else:
                    envs.append(f"{arch:>7} ({os_compose})")
            else:
                envs.append(f"{arch:>7} (container)")
        envs = list(dict.fromkeys(envs))

        # Get time info
        parsed_time = pendulum.parse(request['created'], tz="UTC")
        if show_utc:
            localized_time = parsed_time
        else:
            localized_time = parsed_time.in_timezone(pendulum.local_timezone())  # type: ignore
        time_display = localized_time.to_datetime_string()
        if show_utc:
            time_display += " UTC"

        # Get guest IP from pre-computed map
        user_ip = ip_map.get(request['id'], "<not-yet-available>")

        row = [
            request.get('state', 'unknown'),
            request['id'],  # Show full request ID
            ranch,
            "\n".join(envs),
            user_ip,
            time_display,
        ]

        table.add_row(*row)

    if sys.stdin.isatty():
        console.print(table)
        return

    print(table)


def render_table(
    requests_json: Any, show_token_id: bool, show_time: bool, show_utc: bool, ranch: Optional[str]
) -> None:
    """
    Show list of requests as a table.
    """
    table = Table(show_header=True, header_style="bold magenta", expand=True)

    for column in ["artifacts", "state", "ranch", "type", "env", "git", "created", "started", "finished"]:
        table.add_column(column, justify="left" if column in ["env", "git"] else "center")

    if show_token_id:
        table.add_column("token id")

    def shorten_git_url(url: str) -> Tuple[str, ...]:
        orig_url = url

        url = url.replace("https://github.com/", "[green]     github[/green] ")
        url = url.replace("https://gitlab.com/", "[orange_red1]     gitlab[/orange_red1] ")
        url = url.replace("https://*****@gitlab.com/redhat/", "[dark_orange3]  gitlab-rh[/dark_orange3] ")
        url = url.replace("https://*****@gitlab.com/", "[orange_red1]  gitlab[/orange_red1] ")
        url = url.replace("https://gitlab.cee.redhat.com/", "[dark_orange] gitlab-cee[/dark_orange] ")
        url = url.replace("https://*****@gitlab.cee.redhat.com/", "[dark_orange] gitlab-cee[/dark_orange] ")
        url = url.replace("https://pkgs.devel.redhat.com/", "[red3]       rhel[/red3] ")
        url = url.replace("https://src.fedoraproject.org/", "[bright_blue]     fedora[/bright_blue] ")

        if url == orig_url:
            return "", orig_url

        return tuple(url.rsplit(maxsplit=1))

    def get_state_icon(request):
        """
        Transforms the state and result into a single state of the request
        """
        if request["state"] == "new":
            return "🆕"
        if request["state"] == "queued":
            return "⌛️"
        if request["state"] == "running":
            return "🚀"
        if request["state"] in ("canceled", "cancel-requested"):
            return "🚫"
        if request["state"] == "error":
            return "🔥"
        if request["state"] != "complete":
            exit_error("Invalid state {state}")
        if request["result"]["overall"] == "passed":
            return "✅"
        if request["result"]["overall"] == "failed":
            return "❌"
        if request["result"]["overall"] == "error":
            return "⛔️"
        if request["result"]["overall"] == "skipped":
            return "⤼"
        return "<unknown>"

    for request in sorted(requests_json, key=lambda request: request['created'], reverse=True):
        request_type = "fmf" if request["test"].get("fmf") else "sti"
        request_type_human = "[blue]tmt[/blue]" if request_type == "fmf" else "[yellow]sti[/yellow]"
        url = request['test'][request_type].get('url')
        ref = request['test'][request_type].get('ref')
        artifacts_url = get_artifacts_url(request)
        short_ref = ref[:8] if len(ref) == 40 else ref
        envs = []
        for environment in request['environments_requested']:
            arch = environment['arch']
            os_info = environment.get('os') or {}
            os_compose = os_info.get('compose')
            if os_compose:
                # Check if compose contains disk_image or boot_image and display <hidden-flasher-image> instead
                if len(os_compose) > 20:
                    envs.append(f"{arch:>7} (<too-long>)")
                else:
                    envs.append(f"{arch:>7} ({os_compose})")
            else:
                envs.append(f"{arch:>7} (container)")
        envs = list(dict.fromkeys(envs))  # Remove duplicates while preserving order

        git_type, git_url = shorten_git_url(url)

        # Calculate all three times: created, started, finished
        created_dt = pendulum.parse(request['created'], tz="UTC")
        started_dt = calculate_started_time(request)
        finished_dt = calculate_finished_time(request)

        def format_time_display(dt):
            if dt is None:
                return "N/A"
            localized_time = dt if show_utc else dt.in_timezone(pendulum.local_timezone())
            if show_time:
                display = localized_time.to_datetime_string()
                if show_utc:
                    display += " UTC"
                return display
            else:
                return dt.diff_for_humans()

        created_display = format_time_display(created_dt)
        started_display = format_time_display(started_dt)
        finished_display = format_time_display(finished_dt)

        row = [
            f"[link={artifacts_url}]{request['id']}[/link]" if artifacts_url != '<unavailable>' else '<unavailable>',
            get_state_icon(request),
            get_ranch_colored(artifacts_url),
            f"[yellow]{request_type_human}[/yellow]",
            "\n".join(envs),
            f"{git_type} [link={url}]{git_url}[/link] [green]({short_ref})[/green]",
            created_display,
            started_display,
            finished_display,
        ]

        if show_token_id:
            row.append(request.get('token_id', 'N/A'))

        table.add_row(*row)

    if sys.stdin.isatty():
        console.print(table)
        return

    print(table)


def _format_datetime_str(dt_str, show_utc=False):
    """Formats an ISO datetime string to a more readable format."""

    if not dt_str or dt_str == 'N/A':
        return "N/A"
    try:
        # Parse with pendulum, handling UTC properly
        dt_obj = pendulum.parse(dt_str, tz="UTC")

        if show_utc:
            # Show in UTC
            return dt_obj.format("YYYY-MM-DD [at] HH:mm:ss") + " UTC"
        else:
            # Show in local timezone by default
            local_dt = dt_obj.in_timezone(pendulum.local_timezone())
            tz_name = local_dt.timezone_name
            return local_dt.format("YYYY-MM-DD [at] HH:mm:ss") + f" {tz_name}"
    except (ValueError, TypeError):
        # if parsing fails, return the original string
        return dt_str


def _format_time(seconds):
    """Converts seconds to a human-readable format."""

    if seconds is None:
        return "N/A"
    try:
        seconds = float(seconds)
        minutes, seconds = divmod(seconds, 60)
        return f"{int(minutes)}m {seconds:.2f}s"
    except (ValueError, TypeError):
        return "N/A"


def _has_meaningful_content(data: dict[str, Any]) -> bool:
    """Check if a dictionary has any meaningful content (non-None, non-empty values)."""
    for value in data.values():
        if value is None:
            continue
        if isinstance(value, (list, dict)) and len(value) == 0:
            continue
        if isinstance(value, dict):
            if _has_meaningful_content(value):
                return True
        else:
            return True
    return False


def _print_nested_dict(table: Any, data: dict[str, Any], indent_level: int = 0):
    """Recursively prints a nested dictionary, skipping None values and empty collections."""

    prefix = "  " * indent_level
    for key, value in data.items():
        if value is None:
            continue
        # Skip empty collections (lists, dicts)
        if isinstance(value, (list, dict)) and len(value) == 0:
            continue
        if isinstance(value, dict):
            table.add_row(f"{prefix}[bold]{key}[/bold]", "")
            _print_nested_dict(table, value, indent_level + 1)
        else:
            table.add_row(f"{prefix}{key}", str(value))


def render_text(requests_json: Any, brief: bool, show_utc: bool = False, show_token_id: bool = False) -> None:
    """Show list of requests as a text."""

    header_style = "bold magenta"

    # enumerate and print request metadata
    for i, request_item in enumerate(requests_json):
        if not request_item:
            continue

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column()
        table.add_column()

        # Get artifacts URL and ranch
        artifacts_url = get_artifacts_url(request_item)
        ranch = get_ranch_colored(artifacts_url)

        table.add_row(f"[{header_style}]Artifacts[/{header_style}]", f"[link={artifacts_url}]{artifacts_url}[/link]")
        table.add_row(f"[{header_style}]Ranch[/{header_style}]", ranch)
        table.add_row(f"[{header_style}]State[/{header_style}]", request_item.get('state'))

        if show_token_id:
            table.add_row(f"[{header_style}]Token ID[/{header_style}]", request_item.get('token_id', 'N/A'))
        result = request_item.get('result', {})
        if result:
            table.add_row(f"[{header_style}]Result[/{header_style}]", result.get('overall'))
            if result.get('summary'):
                table.add_row(f"[{header_style}]Summary[/{header_style}]", result.get('summary'))

        table.add_row(
            f"[{header_style}]Created[/{header_style}]",
            _format_datetime_str(request_item.get('created'), show_utc=show_utc),
        )

        # Add started time if available
        started_dt = calculate_started_time(request_item)
        if started_dt:
            started_localized = started_dt if show_utc else started_dt.in_timezone(pendulum.local_timezone())
            started_display = started_localized.format("YYYY-MM-DD [at] HH:mm:ss")
            if show_utc:
                started_display += " UTC"
            else:
                started_display += f" {started_localized.timezone_name}"
            table.add_row(f"[{header_style}]Started[/{header_style}]", started_display)

        # Add finished time if available
        finished_dt = calculate_finished_time(request_item)
        if finished_dt:
            finished_localized = finished_dt if show_utc else finished_dt.in_timezone(pendulum.local_timezone())
            finished_display = finished_localized.format("YYYY-MM-DD [at] HH:mm:ss")
            if show_utc:
                finished_display += " UTC"
            else:
                finished_display += f" {finished_localized.timezone_name}"
            table.add_row(f"[{header_style}]Finished[/{header_style}]", finished_display)

        if not brief:
            table.add_row(
                f"[{header_style}]Queued Time[/{header_style}]", _format_time(request_item.get('queued_time'))
            )
            table.add_row(f"[{header_style}]Run Time[/{header_style}]", _format_time(request_item.get('run_time')))

            if 'test' in request_item and request_item['test']:
                table.add_row(f"[{header_style}]Test[/{header_style}]", "")
                _print_nested_dict(table, request_item['test'], 1)

            if 'environments_requested' in request_item and request_item['environments_requested']:
                table.add_row(f"[{header_style}]Environments[/{header_style}]", "")
                for i, env in enumerate(request_item['environments_requested']):
                    table.add_row(f"  [bold]Environment {i+1}[/bold]", "")
                    _print_nested_dict(table, env, 2)

            if (
                'settings' in request_item
                and request_item.get('settings')
                and _has_meaningful_content(request_item['settings'])
            ):
                table.add_row(f"[{header_style}]Settings[/{header_style}]", "")
                _print_nested_dict(table, request_item['settings'], 1)

            if 'user' in request_item and request_item.get('user') and _has_meaningful_content(request_item['user']):
                table.add_row(f"[{header_style}]User[/{header_style}]", "")
                _print_nested_dict(table, request_item['user'], 1)

        console.print(table)

        # visual boundary between test requests
        if i < len(requests_json) - 1:
            console.print("─" * 15)
        else:
            console.print()


def listing(
    context: typer.Context,
    api_token: str = ARGUMENT_API_TOKEN,
    api_url: str = ARGUMENT_API_URL,
    internal_api_url: str = ARGUMENT_INTERNAL_API_URL,
    states: List[PipelineState] = typer.Option(
        [state for state in PipelineState],
        "--state",
        help=(
            "State of requests to show, by default all requests created in the past day are shown. "
            "Can be specified multiple times."
        ),
    ),
    mine: bool = typer.Option(
        True, '--mine/--all', help="Show only my requests or all requests. By default only your requests are shown."
    ),
    age: Age = typer.Option(
        "1d",
        parser=lambda value: Age.from_string(value),
        metavar="AGE",
        help=(
            "Maximum age of the request (based on created time) represented in [VALUE][UNIT] format. "
            f"Accepted units are: {Age.available_units()}"
        ),
    ),
    min_age: Optional[Age] = typer.Option(
        None,
        parser=lambda value: Age.from_string(value),
        metavar="MINIMUM_AGE",
        help=(
            "Minimum age of the request (based on created time) represented in [VALUE][UNIT] format. "
            f"Accepted units are: {Age.available_units()}"
        ),
    ),
    format: OutputFormat = typer.Option(
        "table", help=f"Output format to use. Possible formats: {OutputFormat.available_formats()}"
    ),
    show_time: bool = typer.Option(
        False, help="Show date instead of human readable diff in text output, i.e. 1 hour ago"
    ),
    show_utc: bool = typer.Option(False, help="Show UTC time instead of local timezone"),
    show_secrets: bool = typer.Option(
        False, help="Show secrets. When listing all requests this requires 'admin' privileges."
    ),
    show_token_id: bool = typer.Option(
        False, "--show-token-id", help="Show token ID submitting the request. Requires admin token."
    ),
    ranch: Optional[Ranch] = typer.Option(
        None,
        help=(
            "For your requests ranch is enforced by the given token. "
            "When listing all requests, you can use this option to restrict listing for a specific ranch"
        ),
    ),
    brief: bool = typer.Option(False, "--brief", help="Show brief output (only basic information)."),
    ids: Optional[List[str]] = typer.Option(
        None, "--id", help="Request ID(s) to show. Can be specified multiple times or contain partial UUID strings."
    ),
    token_id: Optional[str] = typer.Option(
        None, "--token-id", help="Show requests for a specific token ID. Must be a valid UUID4."
    ),
    reserve: bool = typer.Option(False, "-r", "--reserve", help="Show active reservations."),
):
    """
    List Testing Farm requests.

    By default all your requests are shown.

    The ranch is detected from your token.

    State emojis in table format (combine request state and overall result):
    🆕 new, ⌛️ queued, 🚀 running, 🚫 canceled, 🔥 infrastructure error,
    ✅ passed, ❌ failed, ⛔️ test error, ⤼ skipped
    """
    # Accept these arguments only via environment variables
    check_unexpected_arguments(context, "api_url", "api_token")

    # Validate conflicting options
    if ids:
        if context.get_parameter_source("mine") == ParameterSource.COMMANDLINE:
            if mine:
                exit_error(
                    "The '--id' option conflicts with '--mine'. "
                    "When specifying request IDs, ownership filtering is not applicable."
                )
            else:
                exit_error(
                    "The '--id' option conflicts with '--all'. "
                    "When specifying request IDs, ownership filtering is not applicable."
                )

        if context.get_parameter_source("age") == ParameterSource.COMMANDLINE:
            exit_error(
                "The '--id' option conflicts with '--age'. "
                "When specifying request IDs, age filtering is not applicable."
            )

        if context.get_parameter_source("min_age") == ParameterSource.COMMANDLINE:
            exit_error(
                "The '--id' option conflicts with '--min-age'. "
                "When specifying request IDs, age filtering is not applicable."
            )

        if reserve:
            exit_error(
                "The '--reserve' option cannot be used with '--id'. " "Use '--reserve' without specifying request IDs."
            )

    # Validate reserve conflicts with explicit format
    if reserve and context.get_parameter_source("format") == ParameterSource.COMMANDLINE:
        exit_error(
            "The '--reserve' option conflicts with explicit '--format'. "
            "Reservations use a specialized table format that cannot be changed."
        )

    elif show_secrets:
        exit_error("The '--show-secrets' option can be used only with '--id' option.")

    # Validate ranch conflicts with mine
    if mine and ranch:
        exit_error(
            "The '--ranch' option conflicts with '--mine'. "
            "When showing your own requests, ranch filtering is not applicable."
        )

    # Validate token_id
    if token_id:
        # Validate UUID4 format
        if not uuid_valid(token_id, version=4):
            exit_error(f"Invalid token ID '{token_id}'. Token ID must be a valid UUID4.")

        # Check conflicts with mine/all
        if context.get_parameter_source("mine") == ParameterSource.COMMANDLINE:
            if mine:
                exit_error(
                    "The '--token-id' option conflicts with '--mine'. "
                    "Token filtering shows requests for any token, not just yours."
                )
            else:
                exit_error(
                    "The '--token-id' option conflicts with '--all'. "
                    "Token filtering is already specific to the given token."
                )

    # Use internal API if showing secrets, otherwise use public API
    base_url = internal_api_url if show_secrets else api_url

    # Build base URL with age parameter
    url_params = f"created_after={age.to_string()}"

    # Add ranch parameter if specified (only for --all, not --mine)
    if ranch and not mine and not token_id:
        url_params += f"&ranch={ranch.value}"

    # Add token_id parameter if specified
    if token_id:
        url_params += f"&token_id={token_id}"
        # When using token_id, behave like --all (don't use authentication)
        mine = False

    # When using specific request IDs, behave like --all (don't use authentication)
    if ids:
        mine = False

    base_request_url = urllib.parse.urljoin(base_url, f"v0.1/requests?{url_params}")

    # Setting up HTTP retries
    session = requests.Session()
    install_http_retries(session)

    def handle_response_errors(response: requests.Response) -> None:
        if response.status_code == 401:
            exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")

        if response.status_code != 200:
            exit_error(
                f"Unexpected error {response.text}. "
                f"Check {settings.STATUS_PAGE}. "
                f"File an issue to {settings.ISSUE_TRACKER} if needed."
            )

    # Handle minimum age
    if min_age:
        base_request_url = f"{base_request_url}&created_before={min_age.to_string()}"

    # check for token
    if not api_token and (mine or show_secrets):
        exit_error("No API token found, export `TESTING_FARM_API_TOKEN` environment variable")

    # Validate token if provided
    if api_token:
        whoami_url = urllib.parse.urljoin(base_url, "v0.1/whoami")
        try:
            response = session.get(whoami_url, headers=authorization_headers(api_token))
            if response.status_code == 401:
                exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")
            elif response.status_code != 200:
                exit_error(
                    f"Token validation failed with status {response.status_code}. "
                    f"Check {settings.STATUS_PAGE}. "
                    f"File an issue to {settings.ISSUE_TRACKER} if needed."
                )
        except requests.RequestException as e:
            exit_error(f"Failed to validate token: {e}")

    # Handle specific request IDs
    if ids:
        extracted_ids = [extract_uuid(id_string) for id_string in ids]

        # Fetch individual requests
        with Progress(SpinnerColumn(), transient=True) as progress:
            progress.add_task(description="")

            def fetch_individual_request(request_id: str):
                # Use internal API if showing secrets, otherwise use public API

                request_url = urllib.parse.urljoin(base_url, f"v0.1/requests/{request_id}")
                if mine or show_secrets:
                    response = session.get(request_url, headers=authorization_headers(api_token))
                else:
                    response = session.get(request_url)

                if response.status_code == 404:
                    console.print(f"Request {request_id} not found", style="yellow")
                    return None

                handle_response_errors(response)
                return response.json()

            requests_json = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = executor.map(fetch_individual_request, extracted_ids)

            for result in results:
                if result:
                    requests_json.append(result)
    else:
        # Original logic for fetching by states and age
        with Progress(SpinnerColumn(), transient=True) as progress:
            progress.add_task(description="")

            # Lookup only current users requests
            def fetch(url: str):
                if mine:
                    response = session.get(url, headers=authorization_headers(api_token))
                else:
                    response = session.get(url)

                handle_response_errors(response)

                return response.json() or []

            requests_json: List[dict[str, Any]] = []

            urls = (f"{base_request_url}&state={state.value}" for state in states)

            with ThreadPoolExecutor(max_workers=5) as executor:
                results = executor.map(fetch, urls)

            for result in results:
                requests_json.extend(result)

    # For single request ID, default to text format and verbose mode if not explicitly set
    if ids and len(requests_json) == 1:
        if context.get_parameter_source("format") == ParameterSource.DEFAULT:
            format = OutputFormat.text
        if context.get_parameter_source("brief") == ParameterSource.DEFAULT:
            brief = False  # Ensure verbose mode for single requests

    # Validate show-secrets only works with text format (after format adjustments)
    if show_secrets and format != OutputFormat.text:
        exit_error("The '--show-secrets' option only works with text output format. Use '--format' text to force.")

    # Validate brief only works with text format
    if brief and format != OutputFormat.text:
        exit_error("The '--brief' option only works with text output format. Use '--format' text.")

    if format == OutputFormat.json:
        json_dump = json.dumps(requests_json) or '[]'
        console.print_json(json_dump)
        return

    if not requests_json:
        console.print("No requests found")
        return

    if format == OutputFormat.yaml:
        yaml_dump = io.StringIO()
        YAML().dump(requests_json, yaml_dump)
        syntax = Syntax(yaml_dump.getvalue(), 'yaml')
        console.print(syntax)
        return

    if format == OutputFormat.table:
        if reserve:
            render_reservation_table(requests_json=requests_json, show_utc=show_utc)
        else:
            render_table(
                requests_json=requests_json,
                show_token_id=show_token_id,
                show_time=show_time,
                show_utc=show_utc,
                ranch=ranch,
            )
        return

    render_text(requests_json=requests_json, brief=brief, show_utc=show_utc, show_token_id=show_token_id)
