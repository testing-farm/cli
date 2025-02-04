# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import base64
import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import textwrap
import time
import urllib.parse
import xml.etree.ElementTree as ET
from enum import Enum
from typing import Any, Dict, List, Optional

import pkg_resources
import requests
import typer
from click.core import ParameterSource  # pyre-ignore[21]
from rich import print, print_json
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from tft.cli.config import settings
from tft.cli.utils import (
    artifacts,
    cmd_output_or_exit,
    console,
    console_stderr,
    exit_error,
    hw_constraints,
    install_http_retries,
    normalize_multistring_option,
    options_to_dict,
    read_glob_paths,
    uuid_valid,
)

cli_version: str = pkg_resources.get_distribution("tft-cli").version

TestingFarmRequestV1: Dict[str, Any] = {'test': {}, 'environments': None}
Environment: Dict[str, Any] = {'arch': None, 'os': None, 'pool': None, 'artifacts': None, 'variables': {}}
TestTMT: Dict[str, Any] = {'url': None, 'ref': None, 'name': None}
TestSTI: Dict[str, Any] = {'url': None, 'ref': None}

REQUEST_PANEL_TMT = "TMT Options"
REQUEST_PANEL_STI = "STI Options"
REQUEST_PANEL_RESERVE = "Reserve Options"

RESERVE_PANEL_GENERAL = "General Options"
RESERVE_PANEL_ENVIRONMENT = "Environment Options"
RESERVE_PANEL_OUTPUT = "Output Options"

RUN_REPO = "https://gitlab.com/testing-farm/tests"
RUN_PLAN = "/testing-farm/sanity"

RESERVE_PLAN = os.getenv("TESTING_FARM_RESERVE_PLAN", "/testing-farm/reserve")
RESERVE_TEST = os.getenv("TESTING_FARM_RESERVE_TEST", "/testing-farm/reserve-system")
RESERVE_URL = os.getenv("TESTING_FARM_RESERVE_URL", "https://gitlab.com/testing-farm/tests")
RESERVE_REF = os.getenv("TESTING_FARM_RESERVE_REF", "main")
RESERVE_TMT_DISCOVER_EXTRA_ARGS = f"--insert --how fmf --url {RESERVE_URL} --ref {RESERVE_REF} --test {RESERVE_TEST}"

DEFAULT_PIPELINE_TIMEOUT = 60 * 12

# Won't be validating CIDR and 65535 max port range with regex here, not worth it
SECURITY_GROUP_RULE_FORMAT = re.compile(r"(tcp|ip|icmp|udp|-1|[0-255]):(.*):(\d{1,5}-\d{1,5}|\d{1,5}|-1)")


class WatchFormat(str, Enum):
    text = 'text'
    json = 'json'


class PipelineType(str, Enum):
    tmt_multihost = "tmt-multihost"


# Arguments and options that are shared among multiple commands
ARGUMENT_API_URL: str = typer.Argument(
    settings.API_URL, envvar="TESTING_FARM_API_URL", metavar='', rich_help_panel='Environment variables'
)
ARGUMENT_API_TOKEN: str = typer.Argument(
    settings.API_TOKEN,
    envvar="TESTING_FARM_API_TOKEN",
    show_default=False,
    metavar='',
    rich_help_panel='Environment variables',
)
OPTION_TMT_PLAN_NAME: Optional[str] = typer.Option(
    None,
    "--plan",
    help=(
        'Select plans to be executed. '
        'Passed as `--name` option to the `tmt plan` command. '
        'Can be a regular expression.'
    ),
    rich_help_panel=REQUEST_PANEL_TMT,
)
OPTION_TMT_PLAN_FILTER: Optional[str] = typer.Option(
    None,
    "--plan-filter",
    help=(
        'Filter tmt plans. '
        'Passed as `--filter` option to the `tmt plan` command. '
        'By default, `enabled:true` filter is applied. '
        'Plan filtering is similar to test filtering, '
        'see https://tmt.readthedocs.io/en/stable/examples.html#filter-tests for more information.'
    ),
    rich_help_panel=REQUEST_PANEL_TMT,
)
OPTION_TMT_TEST_NAME: Optional[str] = typer.Option(
    None,
    "--test",
    help=(
        'Select tests to be executed. '
        'Passed as `--name` option to the `tmt test` command. '
        'Can be a regular expression.'
    ),
    rich_help_panel=REQUEST_PANEL_TMT,
)
OPTION_TMT_TEST_FILTER: Optional[str] = typer.Option(
    None,
    "--test-filter",
    help=(
        'Filter tmt tests. '
        'Passed as `--filter` option to the `tmt test` command. '
        'It overrides any test filter defined in the plan. '
        'See https://tmt.readthedocs.io/en/stable/examples.html#filter-tests for more information.'
    ),
    rich_help_panel=REQUEST_PANEL_TMT,
)
OPTION_TMT_PATH: str = typer.Option(
    '.',
    '--path',
    help='Path to the metadata tree root. Relative to the git repository root specified by --git-url.',
    rich_help_panel=REQUEST_PANEL_TMT,
)
OPTION_PIPELINE_TYPE: Optional[PipelineType] = typer.Option(None, help="Force a specific Testing Farm pipeline type.")
OPTION_POST_INSTALL_SCRIPT: Optional[str] = typer.Option(
    None, help="Post-install script to run right after the guest boots for the first time."
)
OPTION_SECURITY_GROUP_RULE_INGRESS: Optional[List[str]] = typer.Option(
    None,
    help=(
        "Additional ingress security group rules to be passed to guest in "
        "PROTOCOL:CIDR:PORT format. Multiple rules can be specified as comma separated, "
        "eg. `tcp:109.81.42.42/32:22,142.0.42.0/24:22`. "
        "Supported by AWS only atm."
    ),
)
OPTION_SECURITY_GROUP_RULE_EGRESS: Optional[List[str]] = typer.Option(
    None,
    help=(
        "Additional egress security group rules to be passed to guest in "
        "PROTOCOL:CIDR:PORT format. Multiple rules can be specified as comma separated, "
        "eg. `tcp:109.81.42.42/32:22,142.0.42.0/24:22`. "
        "Supported by AWS only atm."
    ),
)
OPTION_KICKSTART: Optional[List[str]] = typer.Option(
    None,
    metavar="key=value|@file",
    help=(
        "Kickstart specification to customize the guest installation. Expressed as a key=value pair. "
        "For more information about the supported keys see "
        "https://tmt.readthedocs.io/en/stable/spec/plans.html#kickstart. The @ prefix marks a yaml file to load."
    ),
)
OPTION_POOL: Optional[str] = typer.Option(
    None,
    help=(
        "Force pool to provision. By default the most suited pool is used according to the hardware "
        "requirements specified in tmt plans."
    ),
    rich_help_panel=RESERVE_PANEL_ENVIRONMENT,
)
OPTION_REDHAT_BREW_BUILD: List[str] = typer.Option(
    None,
    help="Brew build task IDs or build NVRs to install on the test environment.",
    rich_help_panel=RESERVE_PANEL_ENVIRONMENT,
)
OPTION_FEDORA_KOJI_BUILD: List[str] = typer.Option(
    None,
    help="Koji build task IDs or build NVRs to install on the test environment.",
    rich_help_panel=RESERVE_PANEL_ENVIRONMENT,
)
OPTION_FEDORA_COPR_BUILD: List[str] = typer.Option(
    None,
    help=(
        "Fedora Copr build to install on the test environment, specified using `build-id:chroot-name`"
        ", e.g. 1784470:fedora-32-x86_64."
    ),
    rich_help_panel=RESERVE_PANEL_ENVIRONMENT,
)
OPTION_REPOSITORY: List[str] = typer.Option(
    None,
    help="Repository base url to add to the test environment and install all packages from it.",
    rich_help_panel=RESERVE_PANEL_ENVIRONMENT,
)
OPTION_REPOSITORY_FILE: List[str] = typer.Option(
    None,
    help="URL to a repository file which should be added to /etc/yum.repos.d, e.g. https://example.com/repository.repo",  # noqa
)
OPTION_DRY_RUN: bool = typer.Option(
    False, help="Do not submit a request to Testing Farm, just print it.", rich_help_panel=RESERVE_PANEL_GENERAL
)
OPTION_VARIABLES: Optional[List[str]] = typer.Option(
    None,
    "-e",
    "--environment",
    metavar="key=value|@file",
    help="Variables to pass to the test environment. The @ prefix marks a yaml file to load.",
)
OPTION_SECRETS: Optional[List[str]] = typer.Option(
    None,
    "-s",
    "--secret",
    metavar="key=value|@file",
    help="Secret variables to pass to the test environment. The @ prefix marks a yaml file to load.",
)
OPTION_HARDWARE: List[str] = typer.Option(
    None,
    help=(
        "HW requirements, expressed as key/value pairs. Keys can consist of several properties, "
        "e.g. ``disk.size='>= 40 GiB'``, such keys will be merged in the resulting environment "
        "with other keys sharing the path: ``cpu.family=79`` and ``cpu.model=6`` would be merged, not overwriting "
        "each other. See https://docs.testing-farm.io/Testing%20Farm/0.1/test-request.html#hardware "
        "for the supported hardware selection possibilities."
    ),
)
OPTION_WORKER_IMAGE: Optional[str] = typer.Option(
    None, "--worker-image", help="Force worker container image. Requires Testing Farm developer permissions."
)
OPTION_PARALLEL_LIMIT: Optional[int] = typer.Option(
    None,
    '--parallel-limit',
    help=(
        "Maximum amount of plans to be executed in parallel. Default values are 12 for Public Ranch and 5 for "
        "Red Hat Ranch."
    ),
)
OPTION_TAGS = typer.Option(
    None,
    "-t",
    "--tag",
    metavar="key=value|@file",
    help="Tag cloud resources with given value. The @ prefix marks a yaml file to load.",
)
OPTION_RESERVE: bool = typer.Option(
    False,
    help="Reserve machine after testing, similarly to the `reserve` command.",
    rich_help_panel=REQUEST_PANEL_RESERVE,
)


def _option_autoconnect(panel: str) -> bool:
    return typer.Option(True, help="Automatically connect to the guest via SSH.", rich_help_panel=panel)


def _option_ssh_public_keys(panel: str) -> List[str]:
    return typer.Option(
        ["~/.ssh/*.pub"],
        "--ssh-public-key",
        help="Path to SSH public key(s) used to connect. Supports globbing.",
        rich_help_panel=panel,
    )


def _option_reservation_duration(panel: str) -> int:
    return typer.Option(
        settings.DEFAULT_RESERVATION_DURATION,
        "--duration",
        help="Set the reservation duration in minutes. By default the reservation is for 30 minutes.",
        rich_help_panel=panel,
    )


def _generate_tmt_extra_args(step: str) -> Optional[List[str]]:
    return typer.Option(
        None,
        help=(
            f"Additional options passed to the \"{step}\" step. "
            "Can be specified multiple times for multiple additions."
        ),
        rich_help_panel=REQUEST_PANEL_TMT,
    )


def _sanity_reserve() -> None:
    """
    Sanity checks for reservation support.
    """

    # Check of SSH_AUTH_SOCK is defined
    ssh_auth_sock = os.getenv("SSH_AUTH_SOCK")
    if not ssh_auth_sock:
        exit_error(
            "No 'ssh-agent' seems to be running, it is required for reservations to work, cannot continue.\n"
            "SSH_AUTH_SOCK is not defined, make sure the ssh-agent is running by executing 'eval `ssh-agent`'."
        )

    # Check if SSH_AUTH_SOCK exists
    if not os.path.exists(ssh_auth_sock):
        exit_error(
            "SSH_AUTH_SOCK socket does not exist, make sure the ssh-agent is running by executing 'eval `ssh-agent`'."
        )

    # Check if value of SSH_AUTH_SOCK is socket
    if not stat.S_ISSOCK(os.stat(ssh_auth_sock).st_mode):
        exit_error("SSH_AUTH_SOCK is not a socket, make sure the ssh-agent is running by executing 'eval `ssh-agent`'.")

    # Check if ssh-add -L is not empty
    ssh_add_output = subprocess.run(["ssh-add", "-L"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if ssh_add_output.returncode != 0:
        exit_error("No SSH identities found in the SSH agent. Please run `ssh-add`.")


def _handle_reservation(session, request_id: str, autoconnect: bool = False) -> None:
    """
    Handle the reservation for :py:func:``request`` and :py:func:``restart`` commands.
    """
    # Get artifacts url
    request_url = urllib.parse.urljoin(settings.API_URL, f"/v0.1/requests/{request_id}")
    response = session.get(request_url)
    artifacts_url = response.json()['run']['artifacts']

    try:
        pipeline_log = session.get(f"{artifacts_url}/pipeline.log").text

        if not pipeline_log:
            exit_error(f"Pipeline log was empty. Please file an issue to {settings.ISSUE_TRACKER}.")

    except requests.exceptions.SSLError:
        exit_error(
            textwrap.dedent(
                f"""
            Failed to access Testing Farm artifacts because of SSL validation error.
            If you use Red Hat Ranch please make sure you have Red Hat CA certificates installed.
            Otherwise file an issue to {settings.ISSUE_TRACKER}.
        """
            )
        )
        return

    except requests.exceptions.ConnectionError:
        exit_error(
            textwrap.dedent(
                f"""
            Failed to access Testing Farm artifacts.
            If you use Red Hat Ranch please make sure you are connected to the VPN.
            Otherwise file an issue to {settings.ISSUE_TRACKER}.
        """
            )
        )
        return

    # match any hostname or IP address from gluetool modules log
    guests = re.findall(r'Guest is ready.*root@([\d\w\.-]+)', pipeline_log)

    if not guests:
        exit_error(
            textwrap.dedent(
                f"""
            No guests found to connect to. This is unexpected, please file an issue
            to {settings.ISSUE_TRACKER}.
        """
            )
        )

    if len(guests) > 1:
        for guest in guests:
            console.print(f"🌎 ssh root@{guest}")
        return
    else:
        console.print(f"🌎 ssh root@{guests[0]}")

    if autoconnect:
        os.system(f"ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null root@{guests[0]}")  # noqa: E501


def _localhost_ingress_rule(session: requests.Session) -> str:
    try:
        get_ip = session.get(settings.PUBLIC_IP_CHECKER_URL)
    except requests.exceptions.RequestException as err:
        exit_error(f"Could not get workstation ip to form a security group rule: {err}")

    if get_ip.ok:
        ip = get_ip.text.strip()
        return f"-1:{ip}:-1"

    else:
        exit_error(f"Got {get_ip.status_code} while checking {settings.PUBLIC_IP_CHECKER_URL}")


def _add_reservation(ssh_public_keys: List[str], rules: Dict[str, Any], duration: int, environment: Dict[str, Any]):
    """
    Add discovery of the reservation test to the given environment.
    """
    authorized_keys = read_glob_paths(ssh_public_keys).encode("utf-8")
    if not authorized_keys:
        exit_error(f"No public SSH keys found under {', '.join(ssh_public_keys)}, cannot continue.")

    authorized_keys_bytes = base64.b64encode(authorized_keys)

    if "secrets" not in environment or environment["secrets"] is None:
        environment["secrets"] = {}

    environment["secrets"].update({"TF_RESERVATION_AUTHORIZED_KEYS_BASE64": authorized_keys_bytes.decode("utf-8")})

    if "settings" not in environment or environment["settings"] is None:
        environment["settings"] = {}

    if "provisioning" not in environment["settings"] or environment["settings"]["provisioning"] is None:
        environment["settings"]["provisioning"] = {}

    environment["settings"]["provisioning"].update(rules)

    if "variables" not in environment or environment["variables"] is None:
        environment["variables"] = {}

    environment["variables"].update({"TF_RESERVATION_DURATION": str(duration)})

    if "tmt" not in environment or environment["tmt"] is None:
        environment["tmt"] = {"extra_args": {}}

    if "extra_args" not in environment["tmt"] or environment["tmt"]["extra_args"] is None:
        environment["tmt"]["extra_args"] = {}

    if "discover" not in environment["tmt"]["extra_args"] or environment["tmt"]["extra_args"]["discover"] is None:
        environment["tmt"]["extra_args"]["discover"] = []

    # add reservation if not already present
    if RESERVE_TMT_DISCOVER_EXTRA_ARGS not in environment["tmt"]["extra_args"]["discover"]:
        environment["tmt"]["extra_args"]["discover"].append(RESERVE_TMT_DISCOVER_EXTRA_ARGS)


def _contains_compose(environments: List[Dict[str, Any]]):
    """
    Returns true if any of environments has ``os.compose`` defined.
    """
    for environment in environments:
        if "os" in environment and environment["os"]:
            if "compose" in environment["os"] and environment["os"]["compose"]:
                return True
    return False


# NOTE(ivasilev) Largely borrowed from artemis-cli
def _parse_security_group_rules(ingress_rules: List[str], egress_rules: List[str]) -> Dict[str, Any]:
    """
    Returns a dictionary with ingress/egress rules in TFT request friendly format
    """
    security_group_rules = {}

    def _add_secgroup_rules(sg_type: str, sg_data: List[str]) -> None:
        security_group_rules[sg_type] = []

        for sg_rule in normalize_multistring_option(sg_data):
            matches = re.match(SECURITY_GROUP_RULE_FORMAT, sg_rule)
            if not matches:
                exit_error(f"Bad format of security group rule '{sg_rule}', should be PROTOCOL:CIDR:PORT")  # noqa: E231

            protocol, cidr, port = matches[1], matches[2], matches[3]

            # Let's validate cidr
            try:
                # This way a single ip address will be converted to a valid ip/32 cidr.
                cidr = str(ipaddress.ip_network(cidr))
            except ValueError as err:
                exit_error(f'CIDR {cidr} has incorrect format: {err}')

            # Artemis expectes port_min/port_max, -1 has to be convered to a proper range 0-65535
            port_min = 0 if port == '-1' else int(port.split('-')[0])
            port_max = 65535 if port == '-1' else int(port.split('-')[-1])

            # Add rule for Artemis API
            security_group_rules[sg_type].append(
                {
                    'type': sg_type.split('_')[-1],
                    'protocol': protocol,
                    'cidr': cidr,
                    'port_min': port_min,
                    'port_max': port_max,
                }
            )

    _add_secgroup_rules('security_group_rules_ingress', ingress_rules)
    _add_secgroup_rules('security_group_rules_egress', egress_rules)

    return security_group_rules


def _get_headers(api_key: str) -> Dict[str, str]:
    """
    Return a dict with headers for a request to Testing Farm API.
    Used for authentication.
    """
    return {'Authorization': f'Bearer {api_key}'}


def _parse_xunit(xunit: str):
    """
    A helper that parses xunit file into sets of passed_plans/failed_plans/errored_plans per arch.

    The plans are returned as a {'arch': ['plan1', 'plan2', ..]} map. If it was impossible to deduce architecture
    from a certain plan result (happens in case of early fails / infra issues), the plan will be listed under the 'N/A'
    key.
    """

    def _add_plan(collection: dict, arch: str, plan: ET.Element):
        # NOTE(ivasilev) name property will always be defined at this point, defaulting to '' to make type check happy
        plan_name = plan.get('name', '')
        if arch in collection:
            collection[arch].append(plan_name)
        else:
            collection[arch] = [plan_name]

    failed_plans = {}
    passed_plans = {}
    skipped_plans = {}
    errored_plans = {}

    results_root = ET.fromstring(xunit)
    for plan in results_root.findall('./testsuite'):
        # Try to get information about the environment (stored under ./testing-environment), may be
        # absent if state is undefined
        testing_environment: Optional[ET.Element] = plan.find('./testing-environment[@name="requested"]')
        if not testing_environment:
            console_stderr.print(
                f'Could not find env specifications for {plan.get("name")}, assuming fail for all arches'
            )
            arch = 'N/A'
        else:
            arch_property = testing_environment.find('./property[@name="arch"]')
            if arch_property is None:
                console_stderr.print(f'Could not find arch property for plan {plan.get("name")} results, skipping')
                continue
            # NOTE(ivasilev) arch property will always be defined at this point, defaulting to '' to make type check
            # happy
            arch = arch_property.get('value', '')
        if plan.get('result') == 'passed':
            _add_plan(passed_plans, arch, plan)
        elif plan.get('result') == 'failed':
            _add_plan(failed_plans, arch, plan)
        elif plan.get('result') == 'skipped':
            _add_plan(skipped_plans, arch, plan)
        else:
            _add_plan(errored_plans, arch, plan)

    # Let's remove possible duplicates among N/A errored out tests
    if 'N/A' in errored_plans:
        errored_plans['N/A'] = list(set(errored_plans['N/A']))
    return passed_plans, failed_plans, skipped_plans, errored_plans


def _get_request_summary(request: dict, session: requests.Session):
    """A helper that prepares json summary of the test run"""
    state = request.get('state')
    artifacts_url = (request.get('run') or {}).get('artifacts')
    xpath_url = f'{artifacts_url}/results.xml' if artifacts_url else ''
    xunit = (request.get('result') or {}).get('xunit') or '<testsuites></testsuites>'
    if state not in ['queued', 'running'] and artifacts_url:
        # NOTE(ivasilev) xunit can be None (ex. in case of timed out requests) so let's fetch results.xml and use it
        # as source of truth
        try:
            response = session.get(xpath_url)
            if response.status_code == 200:
                xunit = response.text
        except requests.exceptions.ConnectionError:
            console_stderr.print("Could not get xunit results")
    passed_plans, failed_plans, skipped_plans, errored_plans = _parse_xunit(xunit)
    overall = (request.get("result") or {}).get("overall")
    arches_requested = [env['arch'] for env in request['environments_requested']]

    return {
        'id': request['id'],
        'state': request['state'],
        'artifacts': artifacts_url,
        'overall': overall,
        'arches_requested': arches_requested,
        'errored_plans': errored_plans,
        'failed_plans': failed_plans,
        'skipped_plans': skipped_plans,
        'passed_plans': passed_plans,
    }


def _print_summary_table(summary: dict, format: Optional[WatchFormat], show_details=True):
    if not format == WatchFormat.text:
        # Nothing to do, table is printed only when text output is requested
        return

    def _get_plans_list(collection):
        return list(collection.values())[0] if collection.values() else []

    def _has_plan(collection, arch, plan):
        return plan in collection.get(arch, [])

    # Let's transform plans maps into collection of plans to display plan result per arch statistics
    errored = _get_plans_list(summary['errored_plans'])
    failed = _get_plans_list(summary['failed_plans'])
    skipped = _get_plans_list(summary['skipped_plans'])
    passed = _get_plans_list(summary['passed_plans'])
    generic_info_table = Table(show_header=True, header_style="bold magenta")
    arches_requested = summary['arches_requested']
    artifacts_url = summary['artifacts'] or ''
    for column in summary.keys():
        generic_info_table.add_column(column)
    generic_info_table.add_row(
        summary['id'],
        summary['state'],
        f'[link]{artifacts_url}[/link]',
        summary['overall'],
        ','.join(arches_requested),
        str(len(errored)),
        str(len(failed)),
        str(len(skipped)),
        str(len(passed)),
    )
    console.print(generic_info_table)

    all_plans = sorted(set(errored + failed + skipped + passed))
    details_table = Table(show_header=True, header_style="bold magenta")
    for column in ["plan"] + arches_requested:
        details_table.add_column(column)

    for plan in all_plans:
        row = [plan]
        for arch in arches_requested:
            if _has_plan(summary['passed_plans'], arch, plan):
                res = '[green]pass[/green]'
            elif _has_plan(summary['skipped_plans'], arch, plan):
                res = '[white]skip[/white]'
            elif _has_plan(summary['failed_plans'], arch, plan):
                res = '[red]fail[/red]'
            elif _has_plan(summary['errored_plans'], 'N/A', plan):
                res = '[yellow]error[/yellow]'
            else:
                # If for some reason the plan has not been executed for this arch (this can happen after
                # applying adjust rules) -> don't show anything
                res = None
            row.append(res)
        details_table.add_row(*row)
    if show_details:
        console.print(details_table)


def watch(
    api_url: str = typer.Option(settings.API_URL, help="Testing Farm API URL."),
    id: str = typer.Option(..., help="Request ID to watch"),
    no_wait: bool = typer.Option(False, help="Skip waiting for request completion."),
    format: Optional[WatchFormat] = typer.Option(WatchFormat.text, help="Output format"),
    autoconnect: bool = typer.Option(True, hidden=True),
    reserve: bool = typer.Option(False, hidden=True),
):
    def _console_print(*args, **kwargs):
        """A helper function that will skip printing to console if output format is json"""
        if format == WatchFormat.json:
            return
        console.print(*args, **kwargs)

    """Watch request for completion."""

    if not uuid_valid(id):
        exit_error("invalid request id")

    get_url = urllib.parse.urljoin(api_url, f"/v0.1/requests/{id}")
    current_state: str = ""

    _console_print(f"🔎 api [blue]{get_url}[/blue]")

    if not no_wait:
        _console_print("💡 waiting for request to finish, use ctrl+c to skip", style="bright_yellow")

    artifacts_shown = False

    # Setting up retries
    session = requests.Session()
    install_http_retries(session)

    def _is_reserved(session, request):
        artifacts_url = (request.get('run') or {}).get('artifacts')

        if not artifacts_url:
            return False

        try:
            workdir = re.search(r'href="(.*)" name="workdir"', session.get(f"{artifacts_url}/results.xml").text)
        except requests.exceptions.SSLError:
            exit_error("Artifacts unreachable via SSL, do you have RH CA certificates installed?[/yellow]")

        if workdir:
            # finish early if reservation is running
            if re.search(r"\[\+\] Reservation tick:", session.get(f"{workdir.group(1)}/log.txt").text):
                return True

        return False

    while True:
        try:
            response = session.get(get_url)

        except requests.exceptions.ConnectionError as exc:
            console.print("📛 connection to API failed", style="red")
            raise typer.Exit(code=2) from exc

        if response.status_code == 404:
            exit_error("request with given ID not found")

        if response.status_code != 200:
            exit_error(f"failed to get request: {response.text}")

        request = response.json()

        state = request["state"]

        if state == current_state:
            # check for reservation status and finish early if reserved
            if reserve and _is_reserved(session, request):
                _handle_reservation(session, request["id"], autoconnect)
                return

            time.sleep(1)
            continue

        current_state = state

        request_summary = _get_request_summary(request, session)
        if format == WatchFormat.json:
            console.print(json.dumps(request_summary, indent=2))

        if state == "new":
            _console_print("👶 request is [blue]waiting to be queued[/blue]")

        elif state == "queued":
            _console_print("👷 request is [blue]queued[/blue]")

        elif state == "running":
            _console_print("🚀 request is [blue]running[/blue]")
            _console_print(f"🚢 artifacts [blue]{request['run']['artifacts']}[/blue]")
            artifacts_shown = True

        elif state == "complete":
            if not artifacts_shown:
                _console_print(f"🚢 artifacts [blue]{request['run']['artifacts']}[/blue]")

            overall = request["result"]["overall"]
            if overall in ["passed", "skipped"]:
                _console_print("✅ tests passed", style="green")
                _print_summary_table(request_summary, format)
                raise typer.Exit()

            if overall in ["failed", "error", "unknown"]:
                _console_print(f"❌ tests {overall}", style="red")
                if overall == "error":
                    _console_print(f"{request['result']['summary']}", style="red")
                _print_summary_table(request_summary, format)
                raise typer.Exit(code=1)

        elif state == "error":
            msg = (
                request['result'].get('summary')
                if request['result']
                else '\n'.join(note['message'] for note in request['notes'])
            )
            _console_print(f"📛 pipeline error\n{msg}", style="red")
            _print_summary_table(request_summary, format)
            raise typer.Exit(code=2)

        if no_wait:
            _print_summary_table(request_summary, format, show_details=False)
            raise typer.Exit()

        time.sleep(settings.WATCH_TICK)


def version():
    """Print CLI version"""
    console.print(f"{cli_version}")


def request(
    api_url: str = ARGUMENT_API_URL,
    api_token: str = ARGUMENT_API_TOKEN,
    timeout: int = typer.Option(
        DEFAULT_PIPELINE_TIMEOUT,
        help="Set the timeout for the request in minutes. If the test takes longer than this, it will be terminated.",
    ),
    test_type: str = typer.Option("fmf", help="Test type to use, if not set autodetected."),
    tmt_plan_name: Optional[str] = OPTION_TMT_PLAN_NAME,
    tmt_plan_filter: Optional[str] = OPTION_TMT_PLAN_FILTER,
    tmt_test_name: Optional[str] = OPTION_TMT_TEST_NAME,
    tmt_test_filter: Optional[str] = OPTION_TMT_TEST_FILTER,
    tmt_path: str = OPTION_TMT_PATH,
    sti_playbooks: Optional[List[str]] = typer.Option(
        None,
        "--playbook",
        help="Playbook to run, by default 'tests/tests*.yml', multiple playbooks can be specified.",
        rich_help_panel=REQUEST_PANEL_STI,
    ),
    git_url: Optional[str] = typer.Option(
        None, help="URL of the GIT repository to test. If not set, autodetected from current git repository."
    ),
    git_ref: str = typer.Option(
        "main", help="GIT ref or branch to test. If not set, autodetected from current git repository."
    ),
    git_merge_sha: Optional[str] = typer.Option(
        None, help="GIT ref or branch into which --ref will be merged, if specified."
    ),
    arches: List[str] = typer.Option(["x86_64"], "--arch", help="Hardware platforms of the system to be provisioned."),
    compose: Optional[str] = typer.Option(
        None,
        help="Compose used to provision system-under-test. If not set, tests will expect 'container' provision method specified in tmt plans.",  # noqa
    ),
    hardware: List[str] = OPTION_HARDWARE,
    kickstart: Optional[List[str]] = OPTION_KICKSTART,
    pool: Optional[str] = OPTION_POOL,
    cli_tmt_context: Optional[List[str]] = typer.Option(
        None,
        "-c",
        "--context",
        metavar="key=value|@file",
        help="Context variables to pass to `tmt`. The @ prefix marks a yaml file to load.",
    ),
    variables: Optional[List[str]] = OPTION_VARIABLES,
    secrets: Optional[List[str]] = OPTION_SECRETS,
    tmt_environment: Optional[List[str]] = typer.Option(
        None,
        "-T",
        "--tmt-environment",
        metavar="key=value|@file",
        help=(
            "Environment variables to pass to the tmt process. "
            "Used to configure tmt report plugins like reportportal or polarion. "
            "The @ prefix marks a yaml file to load."
        ),
    ),
    no_wait: bool = typer.Option(False, help="Skip waiting for request completion."),
    worker_image: Optional[str] = OPTION_WORKER_IMAGE,
    redhat_brew_build: List[str] = OPTION_REDHAT_BREW_BUILD,
    fedora_koji_build: List[str] = OPTION_FEDORA_KOJI_BUILD,
    fedora_copr_build: List[str] = OPTION_FEDORA_COPR_BUILD,
    repository: List[str] = OPTION_REPOSITORY,
    repository_file: List[str] = OPTION_REPOSITORY_FILE,
    sanity: bool = typer.Option(False, help="Run Testing Farm sanity test.", rich_help_panel=RESERVE_PANEL_GENERAL),
    tags: Optional[List[str]] = OPTION_TAGS,
    watchdog_dispatch_delay: Optional[int] = typer.Option(
        None,
        help="How long (seconds) before the guest \"is-alive\" watchdog is dispatched. Note that this is implemented only in Artemis service.",  # noqa
    ),
    watchdog_period_delay: Optional[int] = typer.Option(
        None,
        help="How often (seconds) check that the guest \"is-alive\". Note that this is implemented only in Artemis service.",  # noqa
    ),
    dry_run: bool = OPTION_DRY_RUN,
    pipeline_type: Optional[PipelineType] = OPTION_PIPELINE_TYPE,
    post_install_script: Optional[str] = OPTION_POST_INSTALL_SCRIPT,
    security_group_rule_ingress: Optional[List[str]] = OPTION_SECURITY_GROUP_RULE_INGRESS,
    security_group_rule_egress: Optional[List[str]] = OPTION_SECURITY_GROUP_RULE_EGRESS,
    user_webpage: Optional[str] = typer.Option(
        None, help="URL to the user's webpage. The link will be shown in the results viewer."
    ),
    user_webpage_name: Optional[str] = typer.Option(
        None, help="Name of the user's webpage. It will be shown in the results viewer."
    ),
    user_webpage_icon: Optional[str] = typer.Option(
        None, help="URL of the icon of the user's webpage. It will be shown in the results viewer."
    ),
    parallel_limit: Optional[int] = OPTION_PARALLEL_LIMIT,
    tmt_discover: Optional[List[str]] = _generate_tmt_extra_args("discover"),
    tmt_prepare: Optional[List[str]] = _generate_tmt_extra_args("prepare"),
    tmt_finish: Optional[List[str]] = _generate_tmt_extra_args("finish"),
    reserve: bool = OPTION_RESERVE,
    ssh_public_keys: List[str] = _option_ssh_public_keys(REQUEST_PANEL_RESERVE),
    autoconnect: bool = _option_autoconnect(REQUEST_PANEL_RESERVE),
    reservation_duration: int = _option_reservation_duration(REQUEST_PANEL_RESERVE),
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

    if not compose and arches != ['x86_64']:
        exit_error(
            "Without compose the tests run against a container image specified in the plan. "
            "Only 'x86_64' architecture supported in this case."
        )

    if sanity:
        if git_url or tmt_plan_name:
            exit_error(
                "The option [underline]--sanity[/underline] is mutually exclusive with "
                "[underline]--git-url[/underline] and [underline]--plan[/underline]."
            )

        git_url = str(settings.TESTING_FARM_TESTS_GIT_URL)
        tmt_plan_name = str(settings.TESTING_FARM_SANITY_PLAN)

    if reserve:
        _sanity_reserve()

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
        # GitHub: git@gitlab.com:testing-farm/cli.git, git+ssh://git@gitlab.com/spoore/centos_rpms_jq.git
        # Pagure: ssh://git@pagure.io/fedora-ci/messages.git
        assert git_url
        git_url = re.sub(r"^(?:(?:git\+)?ssh://)?git@([^:/]*)[:/](.*)", r"https://\1/\2", git_url)

        # detect git ref
        git_ref = cmd_output_or_exit("git rev-parse --abbrev-ref HEAD", "could not autodetect git ref")

        # in case we have a commit checked out, not a named branch
        if git_ref == "HEAD":
            git_ref = cmd_output_or_exit("git rev-parse HEAD", "could not autodetect git ref")

        # detect test type from local files
        if os.path.exists(os.path.join((tmt_path or ""), ".fmf/version")):
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

    console.print(f"📦 repository [blue]{git_url}[/blue] ref [blue]{git_ref}[/blue] test-type [blue]{test_type}[/blue]")

    pool_info = f"via pool [blue]{pool}[/blue]" if pool else ""
    for arch in arches:
        console.print(f"💻 [blue]{compose or 'container image in plan'}[/blue] on [blue]{arch}[/blue] {pool_info}")

    # test details
    test = TestTMT if test_type == "fmf" else TestSTI
    test["url"] = git_url
    test["ref"] = git_ref

    if git_merge_sha:
        test["merge_sha"] = git_merge_sha

    if tmt_plan_name:
        test["name"] = tmt_plan_name

    if tmt_plan_filter:
        test["plan_filter"] = tmt_plan_filter

    if tmt_test_name:
        test["test_name"] = tmt_test_name

    if tmt_test_filter:
        test["test_filter"] = tmt_test_filter

    if sti_playbooks:
        test["playbooks"] = sti_playbooks

    # environment details
    environments = []
    for arch in arches:
        environment = Environment.copy()
        environment["arch"] = arch
        environment["pool"] = pool
        environment["artifacts"] = []
        environment["tmt"] = {}

        # NOTE(ivasilev) From now on tmt.context will be always set. Even if user didn't request anything then
        # arch requested will be passed into the context
        tmt_context = options_to_dict("tmt context", cli_tmt_context or [])
        if "arch" not in tmt_context:
            # If context distro is not set by the user directly via -c let's set it according to arch requested
            tmt_context["arch"] = arch
        environment["tmt"].update({"context": tmt_context})

        if compose:
            environment["os"] = {"compose": compose}

        if secrets:
            environment["secrets"] = options_to_dict("environment secrets", secrets)

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

        if tmt_environment:
            environment["tmt"].update({"environment": options_to_dict("tmt environment variables", tmt_environment)})

        if tmt_discover or tmt_prepare or tmt_finish:
            if "extra_args" not in environment["tmt"]:
                environment["tmt"]["extra_args"] = {}

        if tmt_discover:
            environment["tmt"]["extra_args"]["discover"] = tmt_discover

        if tmt_prepare:
            environment["tmt"]["extra_args"]["prepare"] = tmt_prepare

        if tmt_finish:
            environment["tmt"]["extra_args"]["finish"] = tmt_finish

        environments.append(environment)

    # Setting up retries
    session = requests.Session()
    install_http_retries(session)

    if reserve:
        if not _contains_compose(environments):
            exit_error("Reservations are not supported with container executions, cannot continue")

        if len(environments) > 1:
            exit_error("Reservations are currently supported for a single plan, cannot continue")

        rules = _parse_security_group_rules([_localhost_ingress_rule(session)], [])

        for environment in environments:
            _add_reservation(
                ssh_public_keys=ssh_public_keys, rules=rules, duration=reservation_duration, environment=environment
            )

        machine_pre = "Machine" if len(environments) == 1 else str(len(environments)) + " machines"
        console.print(f"🛟 {machine_pre} will be reserved after testing")

    if any(
        provisioning_detail
        for provisioning_detail in [
            tags,
            watchdog_dispatch_delay,
            watchdog_period_delay,
            post_install_script,
            security_group_rule_ingress,
            security_group_rule_egress,
        ]
    ):
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

    if post_install_script:
        environments[0]["settings"]["provisioning"]["post_install_script"] = post_install_script

    if security_group_rule_ingress or security_group_rule_egress:
        rules = _parse_security_group_rules(security_group_rule_ingress or [], security_group_rule_egress or [])
        environments[0]["settings"]["provisioning"].update(rules)

    # create final request
    request = TestingFarmRequestV1
    if test_type == "fmf":
        test["path"] = tmt_path
        request["test"]["fmf"] = test
    else:
        request["test"]["sti"] = test

    request["environments"] = environments
    request["settings"] = {}

    if reserve or pipeline_type or parallel_limit:
        request["settings"]["pipeline"] = {}

    # in case the reservation duration is more than the pipeline timeout, adjust also the pipeline timeout
    if reserve:
        if reservation_duration > timeout:
            request["settings"]["pipeline"] = {"timeout": reservation_duration}
            console.print(f"⏳ Maximum reservation time is {reservation_duration} minutes")
        else:
            request["settings"]["pipeline"] = {"timeout": timeout}
            console.print(f"⏳ Maximum reservation time is {timeout} minutes")

    if pipeline_type:
        request["settings"]["pipeline"]["type"] = pipeline_type.value

    if parallel_limit:
        request["settings"]["pipeline"]["parallel-limit"] = parallel_limit

    # worker image
    if worker_image:
        console.print(f"👷 Forcing worker image [blue]{worker_image}[/blue]")
        request["settings"]["worker"] = {"image": worker_image}

    if not user_webpage and (user_webpage_name or user_webpage_icon):
        exit_error("The user-webpage-name and user-webpage-icon can be used only with user-webpage option")

    request["user"] = {}
    if user_webpage:
        request["user"]["webpage"] = {"url": user_webpage, "icon": user_webpage_icon, "name": user_webpage_name}

    # submit request to Testing Farm
    post_url = urllib.parse.urljoin(api_url, "v0.1/requests")

    # dry run
    if dry_run:
        console.print("🔍 Dry run, showing POST json only", style="bright_yellow")
        print_json(json.dumps(request, indent=4, separators=(',', ': ')))
        raise typer.Exit()

    # handle errors
    response = session.post(post_url, json=request, headers=_get_headers(api_token))
    if response.status_code == 401:
        exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")

    if response.status_code == 400:
        exit_error(
            f"Request is invalid. {response.json().get('message') or 'Reason unknown.'}."
            f"\nPlease file an issue to {settings.ISSUE_TRACKER} if unsure."
        )

    if response.status_code != 200:
        print(response.text)
        exit_error(f"Unexpected error. Please file an issue to {settings.ISSUE_TRACKER}.")

    request_id = response.json()['id']

    # Watch the request and handle reservation
    watch(api_url, request_id, no_wait, reserve=reserve, autoconnect=autoconnect, format=WatchFormat.text)


def restart(
    context: typer.Context,
    request_id: str = typer.Argument(..., help="Testing Farm request ID or a string containing it."),
    api_url: str = ARGUMENT_API_URL,
    internal_api_url: str = typer.Argument(
        settings.INTERNAL_API_URL,
        envvar="TESTING_FARM_INTERNAL_API_URL",
        metavar='',
        rich_help_panel='Environment variables',
    ),
    api_token: str = ARGUMENT_API_TOKEN,
    compose: Optional[str] = typer.Option(
        None,
        help="Force compose used to provision test environment.",  # noqa
    ),
    pool: Optional[str] = typer.Option(
        None,
        help="Force pool to provision.",
    ),
    git_url: Optional[str] = typer.Option(None, help="Force URL of the GIT repository to test."),
    git_ref: Optional[str] = typer.Option(None, help="Force GIT ref or branch to test."),
    git_merge_sha: Optional[str] = typer.Option(None, help="Force GIT ref or branch into which --ref will be merged."),
    hardware: List[str] = OPTION_HARDWARE,
    tags: Optional[List[str]] = OPTION_TAGS,
    tmt_plan_name: Optional[str] = OPTION_TMT_PLAN_NAME,
    tmt_plan_filter: Optional[str] = OPTION_TMT_PLAN_FILTER,
    tmt_test_name: Optional[str] = OPTION_TMT_TEST_NAME,
    tmt_test_filter: Optional[str] = OPTION_TMT_TEST_FILTER,
    tmt_path: Optional[str] = OPTION_TMT_PATH,
    tmt_discover: Optional[List[str]] = _generate_tmt_extra_args("discover"),
    tmt_prepare: Optional[List[str]] = _generate_tmt_extra_args("prepare"),
    tmt_finish: Optional[List[str]] = _generate_tmt_extra_args("finish"),
    worker_image: Optional[str] = OPTION_WORKER_IMAGE,
    no_wait: bool = typer.Option(False, help="Skip waiting for request completion."),
    dry_run: bool = OPTION_DRY_RUN,
    pipeline_type: Optional[PipelineType] = OPTION_PIPELINE_TYPE,
    parallel_limit: Optional[int] = OPTION_PARALLEL_LIMIT,
    reserve: bool = OPTION_RESERVE,
    ssh_public_keys: List[str] = _option_ssh_public_keys(REQUEST_PANEL_RESERVE),
    autoconnect: bool = _option_autoconnect(REQUEST_PANEL_RESERVE),
    reservation_duration: int = _option_reservation_duration(REQUEST_PANEL_RESERVE),
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
    get_url = urllib.parse.urljoin(str(internal_api_url), f"v0.1/requests/{_request_id}")

    # Setting up retries
    session = requests.Session()
    install_http_retries(session)

    # Get the request details
    response = session.get(get_url, headers=_get_headers(api_token))

    if response.status_code == 401:
        exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")

    # The API token is valid, but it doesn't own the request
    if response.status_code == 403:
        console.print(
            "⚠️ [yellow] You are not the owner of this request. Any secrets associated with the request will not be included on the restart.[/yellow]"  # noqa: E501
        )
        # Construct URL to the internal API
        get_url = urllib.parse.urljoin(str(api_url), f"v0.1/requests/{_request_id}")

        # Get the request details
        response = session.get(get_url)

    if response.status_code != 200:
        exit_error(f"Unexpected error. Please file an issue to {settings.ISSUE_TRACKER}.")

    request = response.json()

    # Transform to a request
    request['environments'] = request['environments_requested']

    # Remove all keys except test and environments
    for key in list(request):
        if key not in ['test', 'environments']:
            del request[key]

    test = request['test']

    # Remove all empty keys in test
    for key in list(test):
        for subkey in list(test[key] or []):
            if not test[key][subkey]:
                del test[key][subkey]
        if not test[key]:
            del test[key]

    # add test type
    test = request['test'][list(request['test'].keys())[0]]

    if git_url:
        test["url"] = git_url

    if git_ref:
        test["ref"] = git_ref

    if tmt_test_name:
        test["test_name"] = tmt_test_name

    if tmt_test_filter:
        test["test_filter"] = tmt_test_filter

    merge_sha_info = ""
    if git_merge_sha:
        test["merge_sha"] = git_merge_sha
        merge_sha_info = f"merge_sha [blue]{git_merge_sha}[/blue]"

    console.print(f"📦 repository [blue]{test['url']}[/blue] ref [blue]{test['ref']}[/blue] {merge_sha_info}")

    # Set compose
    if compose:
        console.print(f"💻 forcing compose [blue]{compose}[/blue]")
        for environment in request['environments']:
            if environment.get("os") is None:
                environment["os"] = {}
            environment["os"]["compose"] = compose

    if hardware:
        console.print(f"💻 forcing hardware [blue]{' '.join(hardware)}[/blue]")
        for environment in request['environments']:
            environment["hardware"] = hw_constraints(hardware)

    if pool:
        console.print(f"💻 forcing pool [blue]{pool}[/blue]")
        for environment in request['environments']:
            environment["pool"] = pool

    if tmt_discover or tmt_prepare or tmt_finish:
        for environment in request["environments"]:
            if "tmt" not in environment:
                environment["tmt"] = {"extra_args": {}}
            if "extra_args" not in environment["tmt"]:
                environment["tmt"]["extra_args"] = {}

    if tmt_discover:
        for environment in request["environments"]:
            environment["tmt"]["extra_args"]["discover"] = tmt_discover

    if tmt_prepare:
        for environment in request["environments"]:
            environment["tmt"]["extra_args"]["prepare"] = tmt_prepare

    if tmt_finish:
        for environment in request["environments"]:
            environment["tmt"]["extra_args"]["finish"] = tmt_finish

    test_type = "fmf" if "fmf" in request["test"] else "sti"

    if tmt_plan_name:
        if test_type == "sti":
            exit_error("The '--plan' option is compabitble only with 'tmt` tests.")
        request["test"][test_type]["name"] = tmt_plan_name

    if tmt_plan_filter:
        if test_type == "sti":
            exit_error("The '--plan-filter' option is compabitble only with 'tmt` tests.")
        request["test"][test_type]["plan_filter"] = tmt_plan_filter

    if test_type == "fmf":
        # The method explained in https://github.com/fastapi/typer/discussions/668
        if context.get_parameter_source("tmt_path") == ParameterSource.COMMANDLINE:  # pyre-ignore[16]
            request["test"][test_type]["path"] = tmt_path

    # worker image
    if worker_image:
        console.print(f"👷 Forcing worker image [blue]{worker_image}[/blue]")
        request["settings"] = request["settings"] if request.get("settings") else {}
        request["settings"]["worker"] = {"image": worker_image}
        # it is required to have also pipeline key set, otherwise API will fail
        request["settings"]["pipeline"] = request["settings"].get("pipeline", {})

    if pipeline_type or parallel_limit:
        if "settings" not in request:
            request["settings"] = {}
        if "pipeline" not in request["settings"]:
            request["settings"]["pipeline"] = {}

    if pipeline_type:
        request["settings"]["pipeline"]["type"] = pipeline_type.value

    if parallel_limit:
        request["settings"]["pipeline"]["parallel-limit"] = parallel_limit

    if tags:
        for environment in request["environments"]:
            if "settings" not in environment or not environment["settings"]:
                environment["settings"] = {}

            if 'provisioning' not in environment["settings"]:
                environment["settings"]["provisioning"] = {}

            environment["settings"]["provisioning"]["tags"] = options_to_dict("tags", tags)

    if reserve:
        if not _contains_compose(request["environments"]):
            exit_error("Reservations are not supported with container executions, cannot continue")

        if len(request["environments"]) > 1:
            exit_error("Reservations are currently supported for a single plan, cannot continue")

        rules = _parse_security_group_rules([_localhost_ingress_rule(session)], [])

        for environment in request["environments"]:
            _add_reservation(
                ssh_public_keys=ssh_public_keys, rules=rules, duration=reservation_duration, environment=environment
            )

        machine_pre = (
            "Machine" if len(request["environments"]) == 1 else str(len(request["environments"])) + " machines"
        )
        console.print(
            f"🕗 {machine_pre} will be reserved after testing for [blue]{str(reservation_duration)}[/blue] minutes"
        )

    # dry run
    if dry_run:
        console.print("🔍 Dry run, showing POST json only", style="bright_yellow")
        print(json.dumps(request, indent=4, separators=(',', ': ')))
        raise typer.Exit()

    # submit request to Testing Farm
    post_url = urllib.parse.urljoin(str(api_url), "v0.1/requests")

    # handle errors
    response = session.post(post_url, json=request, headers=_get_headers(api_token))
    if response.status_code == 401:
        exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")

    if response.status_code == 400:
        exit_error(
            f"Request is invalid. {response.json().get('message') or 'Reason unknown.'}."
            f"\nPlease file an issue to {settings.ISSUE_TRACKER} if unsure."
        )

    if response.status_code != 200:
        print(response.text)
        exit_error(f"Unexpected error. Please file an issue to {settings.ISSUE_TRACKER}.")

    # watch
    watch(
        str(api_url), response.json()['id'], no_wait, reserve=reserve, autoconnect=autoconnect, format=WatchFormat.text
    )


def run(
    arch: str = typer.Option("x86_64", "--arch", help="Hardware platform of the target machine."),
    compose: Optional[str] = typer.Option(
        None,
        help="Compose used to provision the target machine. If not set, script will be executed aginst `fedora:latest` container.",  # noqa
    ),
    pool: Optional[str] = OPTION_POOL,
    hardware: List[str] = OPTION_HARDWARE,
    variables: Optional[List[str]] = OPTION_VARIABLES,
    secrets: Optional[List[str]] = OPTION_SECRETS,
    dry_run: bool = OPTION_DRY_RUN,
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
        console.print("[blue]🔍 showing POST json[/blue]")
        print(json.dumps(request, indent=4, separators=(',', ': ')))
        if dry_run:
            raise typer.Exit()

    # handle errors
    response = session.post(post_url, json=request, headers=_get_headers(settings.API_TOKEN))
    if response.status_code == 401:
        exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")

    if response.status_code == 400:
        exit_error(f"Request is invalid. Please file an issue to {settings.ISSUE_TRACKER}")

    if response.status_code != 200:
        print(response.text)
        exit_error(f"Unexpected error. Please file an issue to {settings.ISSUE_TRACKER}.")

    id = response.json()['id']
    get_url = urllib.parse.urljoin(str(settings.API_URL), f"/v0.1/requests/{id}")

    if verbose:
        console.print(f"🔎 api [blue]{get_url}[/blue]")

    search: Optional[re.Match[str]] = None

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
                time.sleep(1)
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
            console.print(f"\r🚢 artifacts [blue]{artifacts_url}[/blue]")

        try:
            search = re.search(r'href="(.*)" name="workdir"', session.get(f"{artifacts_url}/results.xml").text)

        except requests.exceptions.SSLError:
            console.print(
                "\r🚫 [yellow]artifacts unreachable via SSL, do you have RH CA certificates installed?[/yellow]"
            )
            console.print(f"\r🚢 artifacts [blue]{artifacts_url}[/blue]")

        except requests.exceptions.ConnectionError:
            console.print("\r🚫 [yellow]artifacts unreachable, are you on VPN?[/yellow]")
            console.print(f"\r🚢 artifacts [blue]{artifacts_url}[/blue]")
            return

    if not search:
        exit_error("Could not find working directory, cannot continue")

    workdir = str(search.groups(1)[0])
    output = f"{workdir}/testing-farm/sanity/execute/data/guest/default-0/testing-farm/script-1/output.txt"

    if verbose:
        console.print(f"\r👷 workdir [blue]{workdir}[/blue]")
        console.print(f"\r📤 output [blue]{output}[/blue]")

    response = session.get(output)
    console.print(response.text, end="")


def reserve(
    ssh_public_keys: List[str] = _option_ssh_public_keys(RESERVE_PANEL_GENERAL),
    reservation_duration: int = _option_reservation_duration(RESERVE_PANEL_GENERAL),
    arch: str = typer.Option(
        "x86_64", help="Hardware platform of the system to be provisioned.", rich_help_panel=RESERVE_PANEL_ENVIRONMENT
    ),
    compose: str = typer.Option(
        "Fedora-Rawhide",
        help="Compose used to provision system-under-test. By default Fedora-Rawhide.",  # noqa
        rich_help_panel=RESERVE_PANEL_ENVIRONMENT,
    ),
    hardware: List[str] = OPTION_HARDWARE,
    tags: Optional[List[str]] = OPTION_TAGS,
    kickstart: Optional[List[str]] = OPTION_KICKSTART,
    pool: Optional[str] = OPTION_POOL,
    fedora_koji_build: List[str] = OPTION_FEDORA_KOJI_BUILD,
    fedora_copr_build: List[str] = OPTION_FEDORA_COPR_BUILD,
    repository: List[str] = OPTION_REPOSITORY,
    repository_file: List[str] = OPTION_REPOSITORY_FILE,
    redhat_brew_build: List[str] = OPTION_REDHAT_BREW_BUILD,
    dry_run: bool = OPTION_DRY_RUN,
    post_install_script: Optional[str] = OPTION_POST_INSTALL_SCRIPT,
    print_only_request_id: bool = typer.Option(
        False,
        help="Output only the request ID.",
        rich_help_panel=RESERVE_PANEL_OUTPUT,
    ),
    autoconnect: bool = _option_autoconnect(RESERVE_PANEL_GENERAL),
    worker_image: Optional[str] = OPTION_WORKER_IMAGE,
    security_group_rule_ingress: Optional[List[str]] = OPTION_SECURITY_GROUP_RULE_INGRESS,
    security_group_rule_egress: Optional[List[str]] = OPTION_SECURITY_GROUP_RULE_EGRESS,
    skip_workstation_access: bool = typer.Option(
        False, help="Do not allow ingress traffic from this workstation's ip to the reserved machine"
    ),
    git_ref: Optional[str] = typer.Option(
        None, help="Force GIT ref or branch. Useful for testing changes to reservation plan."
    ),
):
    """
    Reserve a system in Testing Farm.
    """

    def _echo(message: str) -> None:
        if not print_only_request_id:
            console.print(message)

    _sanity_reserve()

    # check for token
    if not settings.API_TOKEN:
        exit_error("No API token found, export `TESTING_FARM_API_TOKEN` environment variable.")

    pool_info = f"via pool [blue]{pool}[/blue]" if pool else ""
    console.print(f"💻 [blue]{compose}[/blue] on [blue]{arch}[/blue] {pool_info}")

    # test details
    test = TestTMT
    test["url"] = RESERVE_URL
    test["ref"] = git_ref or RESERVE_REF
    test["name"] = RESERVE_PLAN

    # environment details
    environment = Environment.copy()
    environment["arch"] = arch
    environment["pool"] = pool
    environment["artifacts"] = []

    if "settings" not in environment:
        environment["settings"] = {}

    if post_install_script or security_group_rule_ingress or security_group_rule_egress or tags:
        if "settings" not in environment:
            environment["settings"] = {}

    if "provisioning" not in environment["settings"]:
        environment["settings"]["provisioning"] = {}

    if "tags" not in environment["settings"]["provisioning"]:
        environment["settings"]["provisioning"]["tags"] = {}

    # reserve command is for interacting with the guest, and so non-spot instances
    # would be nicer for the user than them getting shocked when they loose their work.
    environment["settings"]["provisioning"]["tags"]["ArtemisUseSpot"] = "false"

    if compose:
        environment["os"] = {"compose": compose}

    if hardware:
        environment["hardware"] = hw_constraints(hardware)

    if tags:
        environment["settings"]["provisioning"]["tags"] = options_to_dict("tags", tags)

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

    if post_install_script:
        environment["settings"]["provisioning"]["post_install_script"] = post_install_script

    # Setting up retries
    session = requests.Session()
    install_http_retries(session)

    if not skip_workstation_access or security_group_rule_ingress or security_group_rule_egress:
        ingress_rules = security_group_rule_ingress or []
        if not skip_workstation_access:
            ingress_rules.append(_localhost_ingress_rule(session))

        rules = _parse_security_group_rules(ingress_rules, security_group_rule_egress or [])
        environment["settings"]["provisioning"].update(rules)

    console.print(f"🕗 Reserved for [blue]{str(reservation_duration)}[/blue] minutes")
    environment["variables"] = {"TF_RESERVATION_DURATION": str(reservation_duration)}

    authorized_keys = read_glob_paths(ssh_public_keys).encode("utf-8")
    if not authorized_keys:
        exit_error(f"No public SSH keys found under {', '.join(ssh_public_keys)}, cannot continue.")

    authorized_keys_bytes = base64.b64encode(authorized_keys)
    environment["secrets"] = {"TF_RESERVATION_AUTHORIZED_KEYS_BASE64": authorized_keys_bytes.decode("utf-8")}

    # create final request
    request = TestingFarmRequestV1
    request["test"]["fmf"] = test

    # worker image
    if worker_image:
        console.print(f"👷 Forcing worker image [blue]{worker_image}[/blue]")
        request["settings"] = request["settings"] if request.get("settings") else {}
        request["settings"]["worker"] = {"image": worker_image}

    request["environments"] = [environment]

    # in case the reservation duration is more than the pipeline timeout, adjust also the pipeline timeout
    if reservation_duration > DEFAULT_PIPELINE_TIMEOUT:
        request["settings"] = {"pipeline": {"timeout": reservation_duration}}
        console.print(f"⏳ Maximum reservation time is {reservation_duration} minutes")
    else:
        console.print(f"⏳ Maximum reservation time is {DEFAULT_PIPELINE_TIMEOUT} minutes")

    # submit request to Testing Farm
    post_url = urllib.parse.urljoin(str(settings.API_URL), "v0.1/requests")

    # dry run
    if dry_run:
        if print_only_request_id:
            console.print("🔍 Dry run, print-only-request-id is set. Nothing will be shown", style="bright_yellow")
        else:
            console.print("🔍 Dry run, showing POST json only", style="bright_yellow")
            print(json.dumps(request, indent=4, separators=(',', ': ')))
        raise typer.Exit()

    # handle errors
    response = session.post(post_url, json=request, headers=_get_headers(settings.API_TOKEN))
    if response.status_code == 401:
        exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")

    if response.status_code == 400:
        exit_error(
            f"Request is invalid. {response.json().get('message') or 'Reason unknown.'}."
            f"\nPlease file an issue to {settings.ISSUE_TRACKER} if unsure."
        )

    if response.status_code != 200:
        print(response.text)
        exit_error(f"Unexpected error. Please file an issue to {settings.ISSUE_TRACKER}.")

    id = response.json()['id']
    get_url = urllib.parse.urljoin(str(settings.API_URL), f"/v0.1/requests/{id}")

    if not print_only_request_id:
        console.print(f"🔎 [blue]{get_url}[/blue]")
    else:
        console.print(id)

    # IP address or hostname of the guest, extracted from pipeline.log
    guest: str = ""

    # wait for the reserve task to reserve the machine
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task_id = None

        if not print_only_request_id:
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
                time.sleep(1)
                continue

            current_state = state

            if state in ["complete", "error"]:
                exit_error("Reservation failed, check API request or contact Testing Farm")

            if not print_only_request_id and task_id is not None:
                progress.update(task_id, description=f"Reservation job is [yellow]{current_state}[/yellow]")

            time.sleep(1)

        while current_state != "ready":
            if not print_only_request_id and task_id:
                progress.update(task_id, description=f"Reservation job is [yellow]{current_state}[/yellow]")

            # get the command output
            artifacts_url = response.json()['run']['artifacts']

            try:
                pipeline_log = session.get(f"{artifacts_url}/pipeline.log").text

                if not pipeline_log:
                    exit_error(f"Pipeline log was empty. Please file an issue to {settings.ISSUE_TRACKER}.")

            except requests.exceptions.SSLError:
                exit_error(
                    textwrap.dedent(
                        f"""
                    Failed to access Testing Farm artifacts because of SSL validation error.
                    If you use Red Hat Ranch please make sure you have Red Hat CA certificates installed.
                    Otherwise file an issue to {settings.ISSUE_TRACKER}.
                """
                    )
                )
                return

            except requests.exceptions.ConnectionError:
                exit_error(
                    textwrap.dedent(
                        f"""
                    Failed to access Testing Farm artifacts.
                    If you use Red Hat Ranch please make sure you are connected to the VPN.
                    Otherwise file an issue to {settings.ISSUE_TRACKER}.
                """
                    )
                )
                return

            if 'Result of testing: ERROR' in pipeline_log:
                exit_error(
                    textwrap.dedent(
                        f"""
                    Failed to run reservation task.
                    Check status page {settings.STATUS_PAGE} for outages.
                    File an issue to {settings.ISSUE_TRACKER} if needed.
                """
                    )
                )

            if '[pre-artifact-installation]' in pipeline_log:
                current_state = "preparing environment"

            elif 'Guest is being provisioned' in pipeline_log:
                current_state = "provisioning resources"

            # match any hostname or IP address from gluetool modules log
            search = re.search(r'Guest is ready.*root@([\d\w\.-]+)', pipeline_log)

            if search and 'execute task #1' in pipeline_log:
                current_state = "ready"
                guest = search.group(1)

            time.sleep(1)

    console.print(f"🌎 ssh root@{guest}")

    if autoconnect:
        os.system(f"ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null root@{guest}")  # noqa: E501


def update():
    """
    Update the CLI tool container image.
    """
    # NOTE: This command is handled by the shell wrapper, see `container/testing-farm` file
    pass


def cancel(
    request_id: str = typer.Argument(
        ..., help="Testing Farm request to cancel. Specified by a request ID or a string containing it."
    ),
    api_url: str = ARGUMENT_API_URL,
    api_token: str = ARGUMENT_API_TOKEN,
):
    """
    Cancel a Testing Farm request.
    """

    # UUID pattern
    uuid_pattern = re.compile('[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')

    # Find the UUID in the string
    uuid_match = uuid_pattern.search(request_id)

    if not uuid_match:
        exit_error(f"Could not find a valid Testing Farm request id in '{request_id}'.")
        return

    if not api_token:
        exit_error("No API token found in the environment, please export 'TESTING_FARM_API_TOKEN' variable.")
        return

    # Extract the UUID from the match object
    _request_id = uuid_match.group()

    # Construct URL to the internal API
    request_url = urllib.parse.urljoin(str(api_url), f"v0.1/requests/{_request_id}")

    # Setting up retries
    session = requests.Session()
    install_http_retries(session)

    # Get the request details
    response = session.delete(request_url, headers=_get_headers(api_token))

    if response.status_code == 401:
        exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")

    if response.status_code == 404:
        exit_error("Request was not found. Verify the request ID is correct.")

    if response.status_code == 204:
        exit_error("Request was already canceled.")

    if response.status_code == 409:
        exit_error("Requeted cannot be canceled, it is already finished.")

    if response.status_code != 200:
        exit_error(f"Unexpected error. Please file an issue to {settings.ISSUE_TRACKER}.")

    console.print("✅ Request [yellow]cancellation requested[/yellow]. It will be canceled soon.")


def encrypt(
    message: str = typer.Argument(..., help="Message to be encrypted."),
    api_url: str = ARGUMENT_API_URL,
    api_token: str = ARGUMENT_API_TOKEN,
    git_url: Optional[str] = typer.Option(
        None,
        help="URL of a GIT repository to which the secret will be tied. If not set, it is detected from the current "
        "git repository.",
    ),
    token_id: Optional[str] = typer.Option(
        None,
        help="Token ID to which the secret will be tied. If not set, Token ID will be detected from provided Token.",
    ),
):
    """
    Create secrets for use in in-repository configuration.
    """

    # check for token
    if not api_token:
        exit_error("No API token found, export `TESTING_FARM_API_TOKEN` environment variable")

    git_available = bool(shutil.which("git"))

    # resolve git repository details from the current repository
    if not git_url:
        if not git_available:
            exit_error("no git url defined")
        git_url = cmd_output_or_exit("git remote get-url origin", "could not auto-detect git url")
        # use https instead git when auto-detected
        # GitLab: git@github.com:containers/podman.git
        # GitHub: git@gitlab.com:testing-farm/cli.git, git+ssh://git@gitlab.com/spoore/centos_rpms_jq.git
        # Pagure: ssh://git@pagure.io/fedora-ci/messages.git
        assert git_url
        git_url = re.sub(r"^(?:(?:git\+)?ssh://)?git@([^:/]*)[:/](.*)", r"https://\1/\2", git_url)

    payload = {'url': git_url, 'message': message}

    if token_id:
        payload['token_id'] = token_id
        console_stderr.print(f'🔒 Encrypting secret for token id {token_id} for repository {git_url}')
    else:
        console_stderr.print(f'🔒 Encrypting secret for your token in repo {git_url}')

    # submit request to Testing Farm
    post_url = urllib.parse.urljoin(api_url, "/v0.1/secrets/encrypt")

    session = requests.Session()
    response = session.post(post_url, json=payload, headers={'Authorization': f'Bearer {api_token}'})

    # handle errors
    if response.status_code == 401:
        exit_error(f"API token is invalid. See {settings.ONBOARDING_DOCS} for more information.")

    if response.status_code == 400:
        exit_error(
            f"Request is invalid. {response.json().get('message') or 'Reason unknown.'}."
            f"\nPlease file an issue to {settings.ISSUE_TRACKER} if unsure."
        )

    if response.status_code != 200:
        console_stderr.print(response.text)
        exit_error(f"Unexpected error. Please file an issue to {settings.ISSUE_TRACKER}.")

    console_stderr.print(
        "💡 See https://docs.testing-farm.io/Testing%20Farm/0.1/test-request.html#secrets-in-repo-config for more "
        "information on how to store the secret in repository."
    )
    console.print(response.text)
