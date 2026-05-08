# SPDX-FileCopyrightText: 2026 Jeremy Prin <prin.jeremy@protonmail.ch>
#
# SPDX-License-Identifier: MIT

"""
Built-in system-call symbols for the Oberon-0 compiler.

This module defines every standard I/O and runtime routine that is available
to Oberon-0 programs without an explicit IMPORT declaration.  Each routine is
represented as a :class:`~oberon0_compiler.sym_table.SystemCall` instance and
is pre-loaded into the global scope by
:meth:`~oberon0_compiler.parser.Parser.add_system_calls` before parsing
begins.

Available system calls
----------------------

+----------------+-------+------------------------------------+---------------+
| Name           | Index | Parameters                         | Return type   |
+================+=======+====================================+===============+
| OpenInput      |   0   | (none)                             | (none)        |
+----------------+-------+------------------------------------+---------------+
| ReadInt        |   1   | VAR var: INTEGER                   | (none)        |
+----------------+-------+------------------------------------+---------------+
| eot            |   2   | (none)                             | INTEGER       |
+----------------+-------+------------------------------------+---------------+
| WriteChar      |   3   | c: INTEGER                         | (none)        |
+----------------+-------+------------------------------------+---------------+
| WriteInt       |   4   | n: INTEGER; w: INTEGER             | (none)        |
+----------------+-------+------------------------------------+---------------+
| WriteLn        |   5   | (none)                             | (none)        |
+----------------+-------+------------------------------------+---------------+

Parameter conventions
---------------------
``by_ref=True``
    The argument is passed *by reference* (similar to a VAR parameter in
    standard Oberon).  The caller must supply a variable whose address is
    forwarded to the callee.  ``ReadInt`` uses this so that the integer that
    was read is written back into the caller's variable.

``by_ref=False``
    The argument is passed *by value*: a copy of the expression result is
    pushed on the stack.

Usage::

    from oberon0_compiler.systemcalls import OpenInput, ReadInt, WriteInt, WriteLn
    from oberon0_compiler.sym_table import SymbolTable

    sym_table = SymbolTable()
    sym_table.new_scope()
    for call in (OpenInput, ReadInt, WriteInt, WriteLn):
        sym_table.add(call)
"""

from . import sym_table as SYM
from .types import integer

# ---------------------------------------------------------------------------
# Formal parameter descriptors shared across multiple system calls
# ---------------------------------------------------------------------------

# ReadInt: single VAR (by-reference) INTEGER parameter
_param_var_int = SYM.FormalParameter(name="var", index=0, type_=integer, by_ref=True)

# WriteChar: single by-value INTEGER parameter (character code)
_param_c = SYM.FormalParameter(name="c", index=0, type_=integer, by_ref=False)

# WriteInt: two by-value INTEGER parameters (value and field width)
_param_n = SYM.FormalParameter(name="n", index=0, type_=integer, by_ref=False)
_param_w = SYM.FormalParameter(name="w", index=1, type_=integer, by_ref=False)

# ---------------------------------------------------------------------------
# System call table
#
# Each entry is (name, params, return_type).  The position in this list
# determines the ``index`` stored in the SystemCall instance, which the code
# generator uses to select the correct WebAssembly import function.
# ---------------------------------------------------------------------------

_CALL_DEFS: list[tuple[str, list[SYM.FormalParameter], SYM.Type | None]] = [
    # 0 - OpenInput: rewind / open the standard input stream
    ("OpenInput", [], None),
    # 1 - ReadInt: read one integer from standard input into a VAR parameter
    ("ReadInt", [_param_var_int], None),
    # 2 - eot: return non-zero when the input stream is exhausted
    ("eot", [], integer),
    # 3 - WriteChar: write a single character (given as its ASCII code)
    ("WriteChar", [_param_c], None),
    # 4 - WriteInt: write an integer right-justified in a field of width w
    ("WriteInt", [_param_n, _param_w], None),
    # 5 - WriteLn: write a newline to the standard output stream
    ("WriteLn", [], None),
]

_system_calls: list[SYM.SystemCall] = [
    SYM.SystemCall(name=name, index=i, params=params, return_type=ret)
    for i, (name, params, ret) in enumerate(_CALL_DEFS)
]

# ---------------------------------------------------------------------------
# Public names
# ---------------------------------------------------------------------------

#: Rewind / open standard input.
OpenInput: SYM.SystemCall = _system_calls[0]

#: Read one integer from standard input into a VAR (by-reference) parameter.
ReadInt: SYM.SystemCall = _system_calls[1]

#: Return non-zero when end-of-input has been reached.
eot: SYM.SystemCall = _system_calls[2]

#: Write a single character to standard output.
WriteChar: SYM.SystemCall = _system_calls[3]

#: Write an integer right-justified in a field of *w* characters.
WriteInt: SYM.SystemCall = _system_calls[4]

#: Write a newline to standard output.
WriteLn: SYM.SystemCall = _system_calls[5]
