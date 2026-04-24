# SPDX-FileCopyrightText: 2026 Jeremy Prin <prin.jeremy@protonmail.ch>
#
# SPDX-License-Identifier: MIT

"""
Oberon-0 compiler package.

Entry point for the ``oberon0-compiler`` command-line tool.
"""

import sys
from pathlib import Path
from typing import Annotated, TypeAlias

import typer
from loguru import logger
from rich.console import Console

from .scanner import Scanner

console = Console()
app = typer.Typer()

FilterDict: TypeAlias = dict[str | None, str | int | bool]

__version__ = "0.1.0"


def version_callback(value: bool) -> None:
    """Print the version string and exit when *--version* is supplied."""
    if value:
        print(f"Oberon0 compiler version: {__version__}")
        raise typer.Exit()


@app.command(context_settings={"ignore_unknown_options": False})
def main(
    source: Annotated[Path, typer.Argument(help="Oberon-0 source file (.mod)")],
    _version: Annotated[
        bool,
        typer.Option("--version", callback=version_callback, is_eager=True),
    ] = False,
    debug: bool = False,
    debug_scanner: bool = False,
) -> None:
    """Oberon-0 compiler."""
    logger.remove()

    level_per_module: FilterDict = {"": "INFO"}

    if debug:
        level_per_module[""] = "DEBUG"
    if debug_scanner:
        level_per_module["oberon0_compiler.scanner"] = "DEBUG"

    _ = logger.add(sys.stdout, filter=level_per_module, level=0)

    scanner = Scanner()
    try:
        with source.open("r") as source_file:
            scanner.open(source_file)
    except OSError as e:
        logger.error(f"Cannot open source file {source}: {e}")
        raise typer.Exit(code=1) from e
