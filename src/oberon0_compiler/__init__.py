# SPDX-FileCopyrightText: 2026 Jeremy Prin <prin.jeremy@protonmail.ch>
#
# SPDX-License-Identifier: MIT

"""
Oberon-0 compiler package.

Entry point for the ``oberon0-compiler`` command-line tool.

The compiler is structured as a multi-pass pipeline:

1. **Scanner** (:mod:`oberon0_compiler.scanner`): reads the source file
   character by character and produces a stream of
   :class:`~oberon0_compiler.token.Token` values.

2. **Parser** (:mod:`oberon0_compiler.parser`): consumes the token stream
   and builds an Abstract Syntax Tree (AST) whose node types are defined in
   :mod:`oberon0_compiler.ast`.  Identifiers are resolved against a scoped
   :class:`~oberon0_compiler.sym_table.SymbolTable` that is pre-populated
   with built-in types and system calls before parsing begins.

3. *(Future passes)* Type checker, code generator, etc.

Command-line usage::

    oberon0-compiler <source.mod> [--debug] [--debug-scanner]

The ``--debug`` flag enables DEBUG-level logging for all modules.
The ``--debug-scanner`` flag enables DEBUG-level logging specifically for
the scanner, which prints every token as it is produced.

When parsing succeeds the reconstructed source text (printed from the AST
via each node's ``__str__`` method) is written to standard output.  This
serves as a sanity check that the parser has correctly captured the
structure of the input program.
"""

import sys
from pathlib import Path
from typing import Annotated, TypeAlias

import typer
from loguru import logger
from rich.console import Console

console = Console()
app = typer.Typer()

FilterDict: TypeAlias = dict[str | None, str | int | bool]

__version__ = "0.2.2"


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
    emit_wasm: Annotated[
        bool,
        typer.Option(
            "--emit-wasm",
            help="Generate a WebAssembly (.wasm) file from the parsed module",
        ),
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            help="Output path for the generated \
            WebAssembly (defaults to <source>.wasm)",
        ),
    ] = None,
) -> None:
    """Oberon-0 compiler.

    Parses *source* according to the simplified Oberon-0 grammar and prints
    a reconstruction of the program derived from the Abstract Syntax Tree.
    """
    logger.remove()

    # Configure log levels per module.
    level_per_module: FilterDict = {"": "INFO"}
    if debug:
        level_per_module[""] = "DEBUG"
    if debug_scanner:
        level_per_module["oberon0_compiler.scanner"] = "DEBUG"

    _ = logger.add(sys.stdout, filter=level_per_module, level=0)

    # Lazy imports: placing these inside main() breaks the circular import
    # chain that arises because parser.py and its dependencies all do
    # "from . import <submodule>", which causes Python (and Sphinx autodoc)
    # to re-enter __init__.py while it is still being initialised.
    from .code_gen import CodeGenerator, CodeGenError  # noqa: PLC0415
    from .parser import Parser, ParserError  # noqa: PLC0415
    from .scanner import Scanner, ScannerError  # noqa: PLC0415

    scanner = Scanner()
    parser = Parser(scanner=scanner)

    try:
        # Keep the file open for the entire parse: the scanner reads the
        # source character by character on demand, so the file handle must
        # remain valid until parsing is complete.
        with source.open("r") as source_file:
            scanner.open(source_file)
            module = parser.parse()
    except OSError as e:
        logger.error(f"Cannot open source file '{source}': {e}")
        raise typer.Exit(code=1) from e
    except ScannerError as e:
        logger.error(f"Scanner error: {e}")
        raise typer.Exit(code=1) from e
    except ParserError as e:
        logger.error(f"Parse error: {e}")
        raise typer.Exit(code=1) from e

    # Pretty-print the AST as reconstructed Oberon-0 source.
    logger.info(f"Successfully parsed module '{module.ident}'")
    console.print(str(module))

    if emit_wasm:
        output_path = out if out is not None else source.with_suffix(".wasm")
        try:
            with output_path.open("wb") as wasm_file:
                CodeGenerator().generate(module, wasm_file)
            logger.info(f"Generated WebAssembly: '{output_path}'")
        except (OSError, CodeGenError) as e:
            logger.error(f"Code generation error: {e}")
            raise typer.Exit(code=1) from e
