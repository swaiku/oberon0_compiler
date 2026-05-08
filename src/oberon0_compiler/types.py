# SPDX-FileCopyrightText: 2026 Jeremy Prin <prin.jeremy@protonmail.ch>
#
# SPDX-License-Identifier: MIT

"""
Built-in type definitions for the Oberon-0 compiler.

This module declares the primitive types that are pre-loaded into the global
scope before any source file is parsed (see :meth:`Parser.add_types`).  Each
type is represented as a :class:`~oberon0_compiler.sym_table.Type` instance
that carries a human-readable name, a unique integer index, and the size of
a value of that type in bytes.

Available types
---------------
integer
    The ``INTEGER`` type (index 0, 4 bytes).  Maps to a 32-bit WebAssembly
    ``i32`` value in the code-generation back-end.
boolean
    The ``BOOLEAN`` type (index 1, 4 bytes).  Also represented as an ``i32``
    in WebAssembly, where ``0`` is *false* and any non-zero value is *true*.

Usage example::

    from oberon0_compiler.types import integer, boolean

    print(integer.name)   # "INTEGER"
    print(integer.size)   # 4
    print(boolean.index)  # 1
"""

from . import sym_table as SYM

# ---------------------------------------------------------------------------
# Type table
# Each entry is (name, size_in_bytes).  The list position determines the
# index stored in the Type instance, which is later used by the code
# generator to select the correct WebAssembly value type.
# ---------------------------------------------------------------------------

_TYPE_DEFS: list[tuple[str, int]] = [
    ("INTEGER", 4),
    ("BOOLEAN", 4),
]

_types: list[SYM.Type] = [
    SYM.Type(name=name, index=i, size=size) for i, (name, size) in enumerate(_TYPE_DEFS)
]

#: The built-in ``INTEGER`` type (32-bit signed integer, index 0).
integer: SYM.Type = _types[0]

#: The built-in ``BOOLEAN`` type (32-bit boolean stored as i32, index 1).
boolean: SYM.Type = _types[1]
