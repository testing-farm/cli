# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import base64
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import pkg_resources
import requests
import typer
from rich import print
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from tft.cli.config import settings
from tft.cli.utils import (
    artifacts,
    blue,
    cmd_output_or_exit,
    exit_error,
    hw_constraints,
    install_http_retries,
    normalize_multistring_option,
    options_to_dict,
    read_glob_paths,
    uuid_valid,
    yellow,
)

cli_version: str = pkg_resources.get_distribution("tft-cli").version

TestingFarmRequestV1: Dict[str, Any] = {'api_key': None, 'test': {}, 'environments': None}
Environment: Dict[str, Any] = {'arch': None, 'os': None, 'pool': None, 'artifacts': None, 'variables': {}}
TestTMT: Dict[str, Any] = {'url': None, 'ref': None, 'name': None}
TestSTI: Dict[str, Any] = {'url': None, 'ref': None}

REQUEST_PANEL_TMT = "TMT Options"
REQUEST_PANEL_STI = "STI Options"

RESERVE_PANEL_GENERAL = "General Options"
RESERVE_PANEL_ENVIRONMENT = "Environment Options"

RUN_REPO = "https://gitlab.com/testing-farm/tests"
RUN_PLAN = "/testing-farm/sanity"

RESERVE_PLAN = os.getenv("TESTING_FARM_RESERVE_PLAN", "/testing-farm/reserve")
RESERVE_URL = os.getenv("TESTING_FARM_RESERVE_URL", "https://gitlab.com/testing-farm/tests")
RESERVE_REF = os.getenv("TESTING_FARM_RESERVE_REF", "main")


def watch(
    api_url: str = typer.Option(settings.API_URL, help="Testing Farm API URL."),
    id: str = typer.Option(..., help="Request ID to watch"),
    no_wait: bool = typer.Option(False, help="Skip waiting for request completion."),
):
    """Watch request for completion."""

    if not uuid_valid(id):
        exit_error("invalid request id")

    get_url = urllib.parse.urljoin(api_url, f"/v0.1/requests/{id}")
    current_state: str = ""

    typer.secho(f"🔎 api {blue(get_url)}")

    if not no_wait:
        typer.secho("💡 waiting for request to finish, use ctrl+c to skip", fg=typer.colors.BRIGHT_YELLOW)

    artifacts_shown = False

    # Setting up retries
    session = requests.Session()
    install_http_retries(session)

    while True:
        try:
            response = session.get(get_url)

        except requests.exceptions.ConnectionError as exc:
            typer.secho("📛 connection to API failed", fg=typer.colors.RED)
            raise typer.Exit(code=2) from exc

        if response.status_code == 404:
            exit_error("request with given ID not found")

        if response.status_code != 200:
            exit_error(f"failed to get request: {response.text}")

        request = response.json()

        state = request["state"]

        if state == current_state:
            continue

        current_state = state

        if state == "new":
            typer.secho(f"👶 request is {blue('waiting to be queued')}")

        elif state == "queued":
            typer.secho(f"👷 request is {blue('queued')}")

        elif state == "running":
            typer.secho(f"🚀 request is {blue('running')}")
            typer.secho(f"🚢 artifacts {blue(request['run']['artifacts'])}")
            artifacts_shown = True

        elif state == "complete":
            if not artifacts_shown:
                typer.secho(f"🚢 artifacts {blue(request['run']['artifacts'])}")

            overall = request["result"]["overall"]
            if overall in ["passed", "skipped"]:
                typer.secho("✅ tests passed", fg=typer.colors.GREEN)
                raise typer.Exit()

            if overall in ["failed", "error", "unknown"]:
                typer.secho(f"❌ tests {overall}", fg=typer.colors.RED)
                if overall == "error":
                    typer.secho(f"{request['result']['summary']}", fg=typer.colors.RED)
                raise typer.Exit(code=1)

        elif state == "error":
            typer.secho(f"📛 pipeline error\n{request['result']['summary']}", fg=typer.colors.RED)
            raise typer.Exit(code=2)

        if no_wait:
            raise typer.Exit()

        time.sleep(settings.WATCH_TICK)


def version():
    """Print CLI version"""
    typer.echo(f"{cli_version}")


def request(
    api_url: str = typer.Argument(
        settings.API_URL, envvar="TESTING_FARM_API_URL", metavar='', rich_help_panel='Environment variables'
    ),
    api_token: str = typer.Argument(
        settings.API_TOKEN,
        envvar="TESTING_FARM_API_TOKEN",
        show_default=False,
        metavar='',
        rich_help_panel='Environment variables',
    ),
    timeout: Optional[int] = typer.Option(
        60 * 12,
        help="Set the timeout for the request in minutes. If the test takes longer than this, it will be terminated. Testing Farm internal default is 12h.",  # noqa
    ),
    test_type: str = typer.Option("fmf", help="Test type to use, if not set autodetected."),
    tmt_plan_regex: Optional[str] = typer.Option(
        None,
        "--plan",
        help="Regex for selecting plans, by default all plans are selected.",
        rich_help_panel=REQUEST_PANEL_TMT,
    ),
    tmt_plan_filter_regex: Optional[str] = typer.Option(
        None,
        "--plan-filter",
        help="Regex for filtering plans, by default only enabled plans are executed.",
        rich_help_panel=REQUEST_PANEL_TMT,
    ),
    tmt_test_filter_regex: Optional[str] = typer.Option(
        None, "--test-filter", help="Regex for filtering tests.", rich_help_panel=REQUEST_PANEL_TMT
    ),
    sti_playbooks: Optional[List[str]] = typer.Option(
        None,
        "--playbook",
        help="Playbook to run, by default 'tests/tests*.yml', multiple playbooks can be specified.",
        rich_help_panel=REQUEST_PANEL_STI,
    ),
    git_url: Optional[str] = typer.Option(
        None, help="URL of the GIT repository to test. If not set autodetected from current git repository."
    ),
    git_ref: str = typer.Option(
        "main", help="GIT ref or branch to test. If not set autodetected from current git repository."
    ),
    arches: List[str] = typer.Option(["x86_64"], "--arch", help="Hardware platforms of the system to be provisioned."),
    compose: Optional[str] = typer.Option(
        None,
        help="Compose used to provision system-under-test. If not set tests will expect 'container' provision method specified in tmt plans.",  # noqa
    ),
    hardware: List[str] = typer.Option(
        None,
        help=(
            "HW requirements, expressed as key/value pairs. Keys can consist of several properties, "
            "e.g. ``disk.space='>= 40 GiB'``, such keys will be merged in the resulting environment "
            "with other keys sharing the path: ``cpu.family=79`` and ``cpu.model=6`` would be merged, "
            "not overwriting each other. See https://tmt.readthedocs.io/en/stable/spec/hardware.html "
            "for the hardware specification."
        ),
    ),
    kickstart: Optional[List[str]] = typer.Option(
        None,
        metavar="key=value",
        help=(
            "Kickstart specification to customize the guest installation. Expressed as a key=value pair. "
            "For more information about the supported keys see "
            "https://tmt.readthedocs.io/en/stable/spec/plans.html#kickstart."
        ),
    ),
    pool: Optional[str] = typer.Option(
        None,
        help="Force pool to provision. By default the most suited pool is used according to the hardware requirements specified in tmt plans.",  # noqa
    ),
    tmt_context: Optional[List[str]] = typer.Option(
        None, "-c", "--context", metavar="key=value", help="Context variables to pass to `tmt`."
    ),
    variables: Optional[List[str]] = typer.Option(
        None, "-e", "--environment", metavar="key=value", help="Variables to pass to the test environment."
    ),
    secrets: Optional[List[str]] = typer.Option(
        None, "-s", "--secret", metavar="key=value", help="Secret variables to pass to the test environment."
    ),
    no_wait: bool = typer.Option(False, help="Skip waiting for request completion."),
    worker_image: Optional[str] = typer.Option(
        None, "--worker-image", help="Force worker container image. Requires Testing Farm developer permissions."
    ),
    redhat_brew_build: List[str] = typer.Option(None, help="Brew build task IDs to install on the test environment."),
    fedora_koji_build: List[str] = typer.Option(None, help="Koji build task IDs to install on the test environment."),
    fedora_copr_build: List[str] = typer.Option(
        None,
        help="Fedora Copr build to install on the test environment, specified using `build-id:chroot-name`, e.g. 1784470:fedora-32-x86_64.",  # noqa
    ),
    repository: List[str] = typer.Option(
        None, help="Repository base url to add to the test environment and install all packages from it."
    ),
    repository_file: List[str] = typer.Option(
        None,
        help="URL to a repository file which should be added to /etc/yum.repos.d, e.g. https://example.com/repository.repo",  # noqa
    ),
    tags: Optional[List[str]] = typer.Option(
        None, "-t", "--tag", metavar="key=value", help="Tag cloud resources with given value."
    ),
    watchdog_dispatch_delay: Optional[int] = typer.Option(
        None,
        help="How long (seconds) before the guest \"is-alive\" watchdog is dispatched. Note that this is implemented only in Artemis service.",  # noqa
    ),
    watchdog_period_delay: Optional[int] = typer.Option(
        None,
        help="How often (seconds) check that the guest \"is-alive\". Note that this is implemented only in Artemis service.",  # noqa
    ),
    dry_run: bool = typer.Option(False, help="Do not submit request, just print it"),
):
    """
    Request testing from Testing Farm.
    """
    # Split comma separated arches
    arches = normalize_multistring_option(arches)

    git_available = bool(shutil.which("git"))

    # check for token
    if not api_token:
        exit_error("No API token found, export `TESTING_FARM_API_TOKEN` environment variable")

    # resolve git repository details from the current repository
    if not git_url:
        if not git_available:
            exit_error("no git url defined")

        # check for uncommited changes
        if git_available and not git_url:
            try:
                subprocess.check_output("git update-index --refresh".split(), stderr=subprocess.STDOUT)
                subprocess.check_output("git diff-index --quiet HEAD --".split(), stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as process:
                if 'fatal:' not in str(process.stdout):
                    exit_error(
                        "Uncommited changes found in current git repository, refusing to continue.\n"
                        "   HINT: When running tests for the current repository, the changes "
                        "must be commited and pushed."
                    )

        git_url = cmd_output_or_exit("git remote get-url origin", "could not auto-detect git url")
        # use https instead git when auto-detected
        # GitLab: git@github.com:containers/podman.git
        # GitHub: git@gitlab.com:testing-farm/cli.git
        # Pagure: ssh://git@pagure.io/fedora-ci/messages.git
        assert git_url
        git_url = re.sub(r"^(?:ssh://)?git@([^:/]*)[:/](.*)", r"https://\1/\2", git_url)

        # detect git ref
        git_ref = cmd_output_or_exit("git rev-parse --abbrev-ref HEAD", "could not autodetect git ref")

        # in case we have a commit checked out, not a named branch
        if git_ref == "HEAD":
            git_ref = cmd_output_or_exit("git rev-parse HEAD", "could not autodetect git ref")

        # detect test type from local files
        if os.path.exists(".fmf/version"):
            test_type = "fmf"
        elif os.path.exists("tests/tests.yml"):
            test_type = "sti"
        else:
            exit_error("no test type defined")

    # make typing happy
    assert git_url is not None

    # STI is not supported against a container
    if test_type == "sti" and compose == "container":
        exit_error("container based testing is not available for 'sti' test type")

    typer.echo(f"📦 repository {blue(git_url)} ref {blue(git_ref)} test-type {blue(test_type)}")

    pool_info = f"via pool {blue(pool)}" if pool else ""
    for arch in arches:
        typer.echo(f"💻 {blue(compose or 'container image in plan')} on {blue(arch)} {pool_info}")

    # test details
    test = TestTMT if test_type == "fmf" else TestSTI
    test["url"] = git_url
    test["ref"] = git_ref

    if tmt_plan_regex:
        test["name"] = tmt_plan_regex

    if tmt_plan_filter_regex:
        test["plan_filter"] = tmt_plan_filter_regex

    if tmt_test_filter_regex:
        test["test_filter"] = tmt_test_filter_regex

    if sti_playbooks:
        test["playbooks"] = sti_playbooks

    # environment details
    environments = []
    for arch in arches:
        environment = Environment.copy()
        environment["arch"] = arch
        environment["pool"] = pool
        environment["artifacts"] = []

        if compose:
            environment["os"] = {"compose": compose}

        if secrets:
            environment["secrets"] = options_to_dict("environment secrets", secrets)

        if tmt_context:
            environment["tmt"] = {"context": options_to_dict("tmt context", tmt_context)}

        if variables:
            environment["variables"] = options_to_dict("environment variables", variables)

        if hardware:
            environment["hardware"] = hw_constraints(hardware)

        if kickstart:
            environment["kickstart"] = options_to_dict("environment kickstart", kickstart)

        if redhat_brew_build:
            environment["artifacts"].extend(artifacts("redhat-brew-build", redhat_brew_build))

        if fedora_koji_build:
            environment["artifacts"].extend(artifacts("fedora-koji-build", fedora_koji_build))

        if fedora_copr_build:
            environment["artifacts"].extend(artifacts("fedora-copr-build", fedora_copr_build))

        if repository:
            environment["artifacts"].extend(artifacts("repository", repository))

        if repository_file:
            environment["artifacts"].extend(artifacts("repository-file", repository_file))

        environments.append(environment)

    if tags or watchdog_dispatch_delay is not None or watchdog_period_delay is not None:
        if "settings" not in environments[0]:
            environments[0]["settings"] = {}

        if 'provisioning' not in environments[0]["settings"]:
            environments[0]["settings"]["provisioning"] = {}

        if tags:
            environments[0]["settings"]["provisioning"]["tags"] = options_to_dict("tags", tags)

        if watchdog_dispatch_delay is not None:
            environments[0]["settings"]["provisioning"]["watchdog-dispatch-delay"] = watchdog_dispatch_delay

        if watchdog_period_delay is not None:
            environments[0]["settings"]["provisioning"]["watchdog-period-delay"] = watchdog_period_delay

    # create final request
    request = TestingFarmRequestV1
    request["api_key"] = api_token
    if test_type == "fmf":
        request["test"]["fmf"] = test
    else:
        request["test"]["sti"] = test

    request["environments"] = environments
    request["settings"] = {}
    request["settings"]["pipeline"] = {"timeout": timeout}

    # worker image
    if worker_image:
        request["settings"]["worker"] = {"image": worker_image}
    # submit request to Testing Farm
    post_url = urllib.parse.urljoin(api_url, "v0.1/requests")

    # Setting up retries
    session = requests.Session()
    install_http_retries(session)

    # dry run
    if dry_run:
        typer.secho("🔍 Dry run, showing POST json only", fg=typer.colors.BRIGHT_YELLOW)
        print(json.dumps(request, indent=4, separators=(',', ': ')))
        raise typer.Exit()

    # handle errors
    response = session.post(post_url, json=request)
    if response.status_code == 404:
        exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")

    if response.status_code == 400:
        exit_error(f"Request is invalid. Please file an issue to {settings.ISSUE_TRACKER}")

    if response.status_code != 200:
        exit_error(f"Unexpected error. Please file an issue to {settings.ISSUE_TRACKER}.")

    # watch
    watch(api_url, response.json()['id'], no_wait)


def restart(
    request_id: str = typer.Argument(..., help="Testing Farm request ID or an string containing it."),
    api_url: str = typer.Argument(
        settings.API_URL, envvar="TESTING_FARM_API_URL", metavar='', rich_help_panel='Environment variables'
    ),
    internal_api_url: str = typer.Argument(
        settings.INTERNAL_API_URL,
        envvar="TESTING_FARM_INTERNAL_API_URL",
        metavar='',
        rich_help_panel='Environment variables',
    ),
    api_token: str = typer.Argument(
        settings.API_TOKEN,
        envvar="TESTING_FARM_API_TOKEN",
        show_default=False,
        metavar='',
        rich_help_panel='Environment variables',
    ),
    compose: Optional[str] = typer.Option(
        None,
        help="Change compose used to provision system-under-test. If not set it will use the compose from the original request.",  # noqa
    ),
    tmt_plan_regex: Optional[str] = typer.Option(
        None,
        "--plan",
        help="Regex for selecting plans, by default all plans are selected.",
        rich_help_panel=REQUEST_PANEL_TMT,
    ),
    tmt_plan_filter_regex: Optional[str] = typer.Option(
        None,
        "--plan-filter",
        help="Regex for filtering plans, by default only enabled plans are executed.",
        rich_help_panel=REQUEST_PANEL_TMT,
    ),
    no_wait: bool = typer.Option(False, help="Skip waiting for request completion."),
    dry_run: bool = typer.Option(False, help="Do not submit request, just print it"),
):
    """
    Restart a Testing Farm request.

    Just pass a request ID or an URL with a request ID to restart it.
    """

    # UUID pattern
    uuid_pattern = re.compile('[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')

    # Find the UUID in the string
    uuid_match = uuid_pattern.search(request_id)

    if not uuid_match:
        exit_error(f"Could not find a valid Testing Farm request id in '{request_id}'.")
        return

    # Extract the UUID from the match object
    _request_id = uuid_match.group()

    # Construct URL to the internal API
    get_url = urllib.parse.urljoin(str(internal_api_url), f"v0.1/requests/{_request_id}?api_key={api_token}")

    # Setting up retries
    session = requests.Session()
    install_http_retries(session)

    # Get the request details
    response = session.get(get_url)

    if response.status_code == 404:
        exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")

    if response.status_code != 200:
        exit_error(f"Unexpected error. Please file an issue to {settings.ISSUE_TRACKER}.")

    request = response.json()

    # Transform to a request
    request['environments'] = request['environments_requested']

    # Remove all keys except test and environments
    for key in list(request):
        if key not in ['test', 'environments']:
            del request[key]

    # Remove all empty keys in test
    for key in list(request['test']):
        for subkey in list(request['test'][key] or []):
            if not request['test'][key][subkey]:
                del request['test'][key][subkey]
        if not request['test'][key]:
            del request['test'][key]

    # Set compose
    if compose:
        typer.echo(f"💻 forcing {blue(compose)}")
        for environment in request['environments']:
            if environment.get("os") is None:
                environment["os"] = {}
            environment["os"]["compose"] = compose

    test_type = "fmf" if "fmf" in request["test"] else "sti"

    if tmt_plan_regex:
        if test_type == "sti":
            exit_error("The '--plan' option is compabitble only with 'tmt` tests.")
        request["test"][test_type]["name"] = tmt_plan_regex

    if tmt_plan_filter_regex:
        if test_type == "sti":
            exit_error("The '--plan-filter' option is compabitble only with 'tmt` tests.")
        request["test"][test_type]["plan_filter"] = tmt_plan_filter_regex

    # Add API key
    request['api_key'] = api_token

    # dry run
    if dry_run:
        typer.secho("🔍 Dry run, showing POST json only", fg=typer.colors.BRIGHT_YELLOW)
        print(json.dumps(request, indent=4, separators=(',', ': ')))
        raise typer.Exit()

    # submit request to Testing Farm
    post_url = urllib.parse.urljoin(str(api_url), "v0.1/requests")

    # handle errors
    response = session.post(post_url, json=request)
    if response.status_code == 404:
        exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")

    if response.status_code == 400:
        print(response.text)
        exit_error(f"Request is invalid. Please file an issue to {settings.ISSUE_TRACKER}")

    if response.status_code != 200:
        exit_error(f"Unexpected error. Please file an issue to {settings.ISSUE_TRACKER}.")

    # watch
    watch(str(api_url), response.json()['id'], no_wait)


def run(
    arch: str = typer.Option("x86_64", "--arch", help="Hardware platform of the target machine."),
    compose: Optional[str] = typer.Option(
        None,
        help="Compose used to provision the target machine. If not set script will be executed aginst `fedora:latest` container.",  # noqa
    ),
    pool: Optional[str] = typer.Option(
        None,
        help="Force Testing Farm provisioning pool. By default the most suitable pool is used according to the hardware requirements.",  # noqa
    ),
    hardware: List[str] = typer.Option(
        None,
        help=(
            "HW requirements, expressed as key/value pairs. Keys can consist of several properties, "
            "e.g. ``disk.space='>= 40 GiB'``, such keys will be merged in the resulting environment "
            "with other keys sharing the path: ``cpu.family=79`` and ``cpu.model=6`` would be merged, "
            "not overwriting each other. See https://tmt.readthedocs.io/en/stable/spec/plans.html#hardware "
            "for the hardware specification."
        ),
    ),
    variables: Optional[List[str]] = typer.Option(
        None, "-e", "--environment", metavar="key=value", help="Variables to pass to the test environment."
    ),
    secrets: Optional[List[str]] = typer.Option(
        None, "-s", "--secret", metavar="key=value", help="Secret variables to pass to the test environment."
    ),
    dry_run: bool = typer.Option(False, help="Do not run, just print request to Testing Farm"),
    verbose: bool = typer.Option(False, help="Be verbose."),
    command: List[str] = typer.Argument(..., help="Command to run. Use `--` to separate COMMAND from CLI options."),
):
    """
    Run an arbitrary script via Testing Farm.
    """

    # check for token
    if not settings.API_TOKEN:
        exit_error("No API token found, export `TESTING_FARM_API_TOKEN` environment variable.")

    # create request
    request = TestingFarmRequestV1
    request["api_key"] = settings.API_TOKEN

    test = TestTMT
    test["url"] = RUN_REPO
    test["ref"] = "main"
    test["name"] = "/testing-farm/sanity"
    request["test"]["fmf"] = test

    environment = Environment.copy()

    environment["arch"] = arch
    environment["pool"] = pool

    if compose:
        environment["os"] = {"compose": compose}

    if secrets:
        environment["secrets"] = options_to_dict("environment secrets", secrets)

    if variables:
        environment["variables"] = options_to_dict("environment variables", variables)

    if hardware:
        environment["hardware"] = hw_constraints(hardware)

    environment["variables"]["SCRIPT"] = " ".join(command)

    request["environments"] = [environment]

    # submit request to Testing Farm
    post_url = urllib.parse.urljoin(str(settings.API_URL), "v0.1/requests")

    # Setting up retries
    session = requests.Session()
    install_http_retries(session)

    # dry run
    if dry_run or verbose:
        typer.secho(blue("🔍 showing POST json"))
        print(json.dumps(request, indent=4, separators=(',', ': ')))
        if dry_run:
            raise typer.Exit()

    # handle errors
    response = session.post(post_url, json=request)
    if response.status_code == 404:
        exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")

    if response.status_code == 400:
        exit_error(f"Request is invalid. Please file an issue to {settings.ISSUE_TRACKER}")

    if response.status_code != 200:
        exit_error(f"Unexpected error. Please file an issue to {settings.ISSUE_TRACKER}.")

    id = response.json()['id']
    get_url = urllib.parse.urljoin(str(settings.API_URL), f"/v0.1/requests/{id}")

    if verbose:
        typer.secho(f"🔎 api {blue(get_url)}")

    # wait for the sanity test to finish
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task(description="Preparing execution environment", total=None)

        current_state: str = ""

        while True:
            try:
                response = session.get(get_url)

            except requests.exceptions.ConnectionError as exc:
                exit_error(f"connection to API failed: {str(exc)}")

            if response.status_code != 200:
                exit_error(f"Failed to get request: {response.text}")

            request = response.json()

            state = request["state"]

            if state == current_state:
                continue

            current_state = state

            if state in ["complete", "error"]:
                break

            time.sleep(1)

        # workaround TFT-1690
        install_http_retries(session, status_forcelist_extend=[404], timeout=60, retry_backoff_factor=0.1)

        # get the command output
        artifacts_url = response.json()['run']['artifacts']

        if verbose:
            typer.secho(f"\r🚢 artifacts {blue(artifacts_url)}")

        try:
            search = re.search(r'href="(.*)" name="workdir"', session.get(f"{artifacts_url}/results.xml").text)

        except requests.exceptions.ConnectionError:
            typer.secho(f"\r🚫 {yellow('artifacts unreachable, are you on VPN?')}")
            typer.secho(f"\r🚢 artifacts {blue(artifacts_url)}")
            return

    if not search:
        exit_error("Could not find working directory, cannot continue")

    assert search
    workdir = str(search.groups(1)[0])
    output = f"{workdir}/testing-farm/sanity/execute/data/guest/default-0/testing-farm/script-1/output.txt"

    if verbose:
        typer.secho(f"\r👷 workdir {blue(workdir)}")
        typer.secho(f"\r📤 output {blue(output)}")

    response = session.get(output)

    console = Console()
    console.print(response.text, end="")


def reserve(
    ssh_public_keys: List[str] = typer.Option(
        ["~/.ssh/*.pub"],
        "--ssh-public-key",
        help="Path to SSH public key added to reserved machine. Supports globbing. By default '~/.ssh/*.pub'.",
        rich_help_panel=RESERVE_PANEL_GENERAL,
    ),
    reservation_duration: int = typer.Option(
        30,
        "--duration",
        help="Set the reservation duration in minutes. By default the reservation is for 30 minutes.",
        rich_help_panel=RESERVE_PANEL_GENERAL,
    ),
    arch: str = typer.Option(
        "x86_64", help="Hardware platform of the system to be provisioned.", rich_help_panel=RESERVE_PANEL_ENVIRONMENT
    ),
    compose: str = typer.Option(
        "Fedora-Rawhide",
        help="Compose used to provision system-under-test. By default Fedora-Rawhide.",  # noqa
        rich_help_panel=RESERVE_PANEL_ENVIRONMENT,
    ),
    hardware: List[str] = typer.Option(
        None,
        help=(
            "HW requirements, expressed as key/value pairs. Keys can consist of several properties, "
            "e.g. ``disk.space='>= 40 GiB'``, such keys will be merged in the resulting environment "
            "with other keys sharing the path: ``cpu.family=79`` and ``cpu.model=6`` would be merged, "
            "not overwriting each other. See https://tmt.readthedocs.io/en/stable/spec/hardware.html "
            "for the hardware specification."
        ),
        rich_help_panel=RESERVE_PANEL_ENVIRONMENT,
    ),
    kickstart: Optional[List[str]] = typer.Option(
        None,
        metavar="key=value",
        help=(
            "Kickstart specification to customize the guest installation. Expressed as a key=value pair. "
            "For more information about the supported keys see "
            "https://tmt.readthedocs.io/en/stable/spec/plans.html#kickstart."
        ),
        rich_help_panel=RESERVE_PANEL_ENVIRONMENT,
    ),
    pool: Optional[str] = typer.Option(
        None,
        help=(
            "Force pool to provision. By default the most suited pool is used according to the hardware "
            "requirements specified in tmt plans."
        ),
        rich_help_panel=RESERVE_PANEL_ENVIRONMENT,
    ),
    fedora_koji_build: List[str] = typer.Option(
        None, help="Koji build task IDs to install on the test environment.", rich_help_panel=RESERVE_PANEL_ENVIRONMENT
    ),
    fedora_copr_build: List[str] = typer.Option(
        None,
        help=(
            "Fedora Copr build to install on the test environment, specified using `build-id:chroot-name`"
            ", e.g. 1784470:fedora-32-x86_64."
        ),
        rich_help_panel=RESERVE_PANEL_ENVIRONMENT,
    ),
    repository: List[str] = typer.Option(
        None,
        help="Repository base url to add to the test environment and install all packages from it.",
        rich_help_panel=RESERVE_PANEL_ENVIRONMENT,
    ),
    repository_file: List[str] = typer.Option(
        None,
        help="URL to a repository file which should be added to /etc/yum.repos.d, e.g. https://example.com/repository.repo",  # noqa
    ),
    redhat_brew_build: List[str] = typer.Option(
        None, help="Brew build task IDs to install on the test environment.", rich_help_panel=RESERVE_PANEL_ENVIRONMENT
    ),
    dry_run: bool = typer.Option(
        False, help="Do not submit a request to Testing Farm, just print it.", rich_help_panel=RESERVE_PANEL_GENERAL
    ),
):
    """
    Reserve a system in Testing Farm.
    """

    # check for token
    if not settings.API_TOKEN:
        exit_error("No API token found, export `TESTING_FARM_API_TOKEN` environment variable.")

    pool_info = f"via pool {blue(pool)}" if pool else ""
    typer.echo(f"💻 {blue(compose)} on {blue(arch)} {pool_info}")

    # test details
    test = TestTMT
    test["url"] = RESERVE_URL
    test["ref"] = RESERVE_REF
    test["name"] = RESERVE_PLAN

    # environment details
    environment = Environment.copy()
    environment["arch"] = arch
    environment["pool"] = pool
    environment["artifacts"] = []

    if compose:
        environment["os"] = {"compose": compose}

    if hardware:
        environment["hardware"] = hw_constraints(hardware)

    if kickstart:
        environment["kickstart"] = options_to_dict("environment kickstart", kickstart)

    if redhat_brew_build:
        environment["artifacts"].extend(artifacts("redhat-brew-build", redhat_brew_build))

    if fedora_koji_build:
        environment["artifacts"].extend(artifacts("fedora-koji-build", fedora_koji_build))

    if fedora_copr_build:
        environment["artifacts"].extend(artifacts("fedora-copr-build", fedora_copr_build))

    if repository:
        environment["artifacts"].extend(artifacts("repository", repository))

    if repository_file:
        environment["artifacts"].extend(artifacts("repository-file", repository_file))

    typer.echo(f"🕗 Reserved for {blue(str(reservation_duration))} minutes")
    environment["variables"] = {"TF_RESERVATION_DURATION": str(reservation_duration)}

    # set public keys, pass as a secret
    authorized_keys = read_glob_paths(ssh_public_keys).encode("utf-8")
    if not authorized_keys:
        exit_error("No public SSH key found, they are required for accessing the machines.")

    authorized_keys_bytes = base64.b64encode(authorized_keys)
    environment["secrets"] = {"TF_RESERVATION_AUTHORIZED_KEYS_BASE64": authorized_keys_bytes.decode("utf-8")}

    # create final request
    request = TestingFarmRequestV1
    request["api_key"] = settings.API_TOKEN
    request["test"]["fmf"] = test

    request["environments"] = [environment]

    # submit request to Testing Farm
    post_url = urllib.parse.urljoin(str(settings.API_URL), "v0.1/requests")

    # Setting up retries
    session = requests.Session()
    install_http_retries(session)

    # dry run
    if dry_run:
        typer.secho("🔍 Dry run, showing POST json only", fg=typer.colors.BRIGHT_YELLOW)
        print(json.dumps(request, indent=4, separators=(',', ': ')))
        raise typer.Exit()

    # handle errors
    response = session.post(post_url, json=request)
    if response.status_code == 404:
        exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")

    if response.status_code == 400:
        exit_error(f"Request is invalid. Please file an issue to {settings.ISSUE_TRACKER}")

    if response.status_code != 200:
        exit_error(f"Unexpected error. Please file an issue to {settings.ISSUE_TRACKER}.")

    id = response.json()['id']
    get_url = urllib.parse.urljoin(str(settings.API_URL), f"/v0.1/requests/{id}")

    typer.secho(f"🔎 {blue(get_url)}")

    # IP address or hostname of the guest, extracted from pipeline.log
    guest: str = ""

    # wait for the reserve task to reserve the machine
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task_id = progress.add_task(description="Creating reservation", total=None)

        current_state: str = ""

        while current_state != "running":
            try:
                response = session.get(get_url)

            except requests.exceptions.ConnectionError as exc:
                exit_error(f"connection to API failed: {str(exc)}")

            if response.status_code != 200:
                exit_error(f"Failed to get request: {response.text}")

            request = response.json()

            state = request["state"]

            if state == current_state:
                continue

            current_state = state

            if state in ["complete", "error"]:
                exit_error("Reservation failed, check API request or contact Testing Farm")

            progress.update(task_id, description=f"Reservation job is {yellow(current_state)}")

            time.sleep(1)

        while current_state != "ready":
            progress.update(task_id, description=f"Reservation job is {yellow(current_state)}")

            # get the command output
            artifacts_url = response.json()['run']['artifacts']

            try:
                pipeline_log = session.get(f"{artifacts_url}/pipeline.log").text

                if not pipeline_log:
                    exit_error(f"Pipeline log was empty. Please file an issue to {settings.ISSUE_TRACKER}.")

            except requests.exceptions.ConnectionError:
                exit_error(
                    f"""
                    Failed to access Testing Farm artifacts.
                    If you use Red Hat Ranch please make sure you are conneted to the VPN.
                    Otherwise file an issue to {settings.ISSUE_TRACKER}.
                """
                )
                return

            if '[pre-artifact-installation]' in pipeline_log:
                current_state = "preparing environment"

            elif 'Guest is being provisioned' in pipeline_log:
                current_state = "provisioning resources"

            # match any hostname or IP address, slash to cover case of colored output
            search = re.search(r'guest: ([\d\w\.-]+)', pipeline_log)

            if search:
                current_state = "ready"
                guest = search.group(1)
                continue

            time.sleep(1)

    typer.secho(f"🌎 ssh root@{guest}")

    os.system(f"ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null root@{guest}")
