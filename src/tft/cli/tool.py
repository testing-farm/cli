# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import os

import typer

import tft.cli.commands as commands
from tft.cli.command.composes import composes
from tft.cli.command.listing import listing
from tft.cli.config import settings

app = typer.Typer()


@app.callback()
def main(
    debug: bool = typer.Option(
        False,
        "--debug",
        envvar="TESTING_FARM_DEBUG",
        help="Print the full traceback with local variables on unexpected errors.",
        rich_help_panel='Environment variables',
    ),
) -> None:
    """Testing Farm CLI."""
    # Typer reads these attributes when rendering an unhandled exception (in Typer.__call__),
    # which happens after this callback runs, so flipping them here enables a full traceback.
    if debug:
        app.pretty_exceptions_show_locals = True
        app.pretty_exceptions_short = False


app.command()(commands.cancel)
app.command()(composes)
app.command(name="list")(listing)
app.command()(commands.request)
app.command()(commands.restart)
app.command()(commands.reserve)
app.command()(commands.run)
app.command()(commands.version)
app.command()(commands.watch)
app.command()(commands.encrypt)

# This command is available only for the container based deployment
if os.path.exists(settings.CONTAINER_SIGN):
    app.command()(commands.update)

# Expose REQUESTS_CA_BUNDLE in the environment for RHEL-like systems
# This is needed for custom CA certificates to nicely work.
if "REQUESTS_CA_BUNDLE" not in os.environ and os.path.exists(settings.REQUESTS_CA_BUNDLE):
    os.environ["REQUESTS_CA_BUNDLE"] = settings.REQUESTS_CA_BUNDLE
