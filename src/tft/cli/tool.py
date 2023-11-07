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
