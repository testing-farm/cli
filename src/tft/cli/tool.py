# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import typer

import tft.cli.commands as commands

app = typer.Typer()

app.command()(commands.request)
app.command()(commands.restart)
app.command()(commands.version)
app.command()(commands.watch)
