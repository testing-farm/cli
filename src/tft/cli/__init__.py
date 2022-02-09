# Copyright Contributors to the Testing Farm project.
# SPDX-License-Identifier: Apache-2.0

import pkg_resources
import typer

cli_version: str = pkg_resources.get_distribution("tft-cli").version

app = typer.Typer()


@app.command()
def version():
    """Print CLI version"""
    typer.echo(f'{cli_version}')


@app.command()
def request():
    """Request testing from Testing Farm"""
    typer.echo('📢 One day I will contact Testing Farm')
