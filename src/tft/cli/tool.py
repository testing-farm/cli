# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import os

import typer

import tft.cli.commands as commands
from tft.cli.config import settings

app = typer.Typer()

app.command()(commands.cancel)
app.command()(commands.request)
app.command()(commands.restart)
app.command()(commands.reserve)
app.command()(commands.run)
app.command()(commands.version)
app.command()(commands.watch)

# This command is available only for the container based deployment
if os.path.exists(settings.CONTAINER_SIGN):
    app.command()(commands.update)

# Expose REQUESTS_CA_BUNDLE in the environment for RHEL-like systems
# This is needed for custom CA certificates to nicely work.
if "REQUESTS_CA_BUNDLE" not in os.environ and os.path.exists(settings.REQUESTS_CA_BUNDLE):
    os.environ["REQUESTS_CA_BUNDLE"] = settings.REQUESTS_CA_BUNDLE
