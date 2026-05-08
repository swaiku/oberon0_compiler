# SPDX-FileCopyrightText: 2026 Jeremy Prin <prin.jeremy@protonmail.ch>
#
# SPDX-License-Identifier: MIT

"""
Oberon-0 Symbol Table
=====================

This module implements a scoped symbol table for the Oberon-0 compiler.
It is used by the parser (see :mod:`oberon0_compiler.parser`) to:

  * associate compile-time information with every identifier (name, type,
    memory offset, etc.);
  * resolve identifiers quickly during parsing and semantic analysis;
  * manage lexical scopes so that local names declared inside a procedure
    are not visible outside of it;
  * detect duplicate declarations within the same scope.

Symbol hierarchy
----------------

::

    Symbol
    +-- Type                  (INTEGER, BOOLEAN, ...)
    +-- Variable              (abstract base for variable-like symbols)
    |   +-- LocalVariable     (VAR declared inside a procedure)
    |   +-- GlobalVariable    (VAR declared at module level)
    |   +-- FormalParameter   (future: procedure parameter)
    +-- ProcedureDefinition   (user-defined PROCEDURE)
    +-- SystemCall            (built-in I/O routines)

Scope management
----------------

A :class:`SymbolTable` maintains a stack of :class:`Scope` objects.
Calling :meth:`SymbolTable.new_scope` pushes a fresh scope onto the stack
(e.g. when entering a procedure body).  Calling
:meth:`SymbolTable.close_scope` pops it (e.g. when leaving the procedure).
Identifier lookup searches scopes from innermost to outermost, so a local
name shadows any outer name with the same spelling.

Scanner reference
-----------------

The scanner is:
  :class:`~oberon0_compiler.scanner.Scanner`
"""

from dataclasses import dataclass, field

from loguru import logger

# ---------------------------------------------------------------------------
# Base symbol and concrete symbol types
# ---------------------------------------------------------------------------


@dataclass
class Symbol:
    """Base class for every entry in the symbol table.

    Attributes:
        name: The Oberon-0 identifier as it appears in the source text.
    """

    name: str


@dataclass
class Type(Symbol):
    """A named type (e.g. INTEGER or BOOLEAN).

    Attributes:
        index:  Unique ordinal used by the code generator to identify the type.
        size:   Storage size in bytes (e.g. 4 for a 32-bit integer).
    """

    index: int
    size: int


@dataclass
class Variable(Symbol):
    """Abstract base for all variable-like symbols.

    Concrete sub-classes add the information needed to locate the variable
    at run time (an offset into a frame or a global data segment).

    Attributes:
        type_: The declared :class:`Type` of this variable.
    """

    type_: Type


@dataclass
class LocalVariable(Variable):
    """A variable declared with VAR inside a procedure body.

    Attributes:
        offset: Byte offset from the start of the procedure's local frame.
    """

    offset: int


@dataclass
class GlobalVariable(Variable):
    """A variable declared with VAR at module (global) level.

    Attributes:
        offset: Byte offset from the start of the module's data segment.
    """

    offset: int


@dataclass
class FormalParameter(Variable):
    """A formal parameter of a procedure (reserved for future use).

    Attributes:
        index:  Zero-based position of the parameter in the parameter list.
        by_ref: ``True`` when the parameter is passed by reference (VAR param).
    """

    index: int
    by_ref: bool


@dataclass
class ProcedureDefinition(Symbol):
    """A user-defined procedure declared with the PROCEDURE keyword.

    Attributes:
        exported:   ``True`` when the procedure is marked with ``*`` and
                    therefore visible outside the enclosing module.
        stack_size: Total size in bytes of the procedure's local frame
                    (filled in after the body has been fully parsed).
    """

    exported: bool
    stack_size: int


@dataclass
class SystemCall(Symbol):
    """A built-in system routine (OpenInput, ReadInt, WriteInt, etc.).

    System calls are pre-populated in the global scope before parsing begins
    (see :meth:`~oberon0_compiler.parser.Parser.add_system_calls`).

    Attributes:
        index:       Unique ordinal used by the code generator to select the
                     correct WebAssembly import.
        params:      Ordered list of formal parameters for arity checking.
        return_type: The :class:`Type` returned by the call, or ``None`` for
                     procedures that do not return a value.
    """

    index: int
    params: list[FormalParameter]
    return_type: Type | None = None


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


@dataclass
class Scope:
    """A single lexical scope (one entry in the scope stack).

    Each module and each procedure body opens exactly one scope.  Symbols
    defined at that nesting level are stored in :attr:`symbols`.

    Attributes:
        level:   Nesting depth, starting at 0 for the global module scope.
        symbols: Mapping from identifier spelling to its :class:`Symbol`.
    """

    level: int
    symbols: dict[str, Symbol] = field(default_factory=dict)

    def add(self, symbol: Symbol) -> None:
        """Register *symbol* in this scope.

        Args:
            symbol: The symbol to register.

        Raises:
            KeyError: If an identifier with the same name is already defined
                      in **this** scope (shadowing outer scopes is allowed).
        """
        if symbol.name in self.symbols:
            raise KeyError(
                f"Symbol '{symbol.name}' is already defined in scope {self.level}"
            )
        self.symbols[symbol.name] = symbol
        logger.debug(f"Scope {self.level}: added {symbol}")

    def find(self, name: str, class_: type) -> Symbol | None:
        """Look up *name* in this scope and return it if it is an instance of *class_*.

        Args:
            name:    The identifier to search for.
            class_:  Required class (e.g. :class:`Variable` or :class:`Type`).
                     Pass :class:`Symbol` to accept any kind of symbol.

        Returns:
            The matching :class:`Symbol`, or ``None`` if not found or not of
            the requested class.
        """
        logger.debug(f"Scope {self.level}: looking for '{name}'")
        if name in self.symbols:
            s = self.symbols[name]
            if isinstance(s, class_):
                logger.debug(f"Scope {self.level}: found {s}")
                return s
        return None


# ---------------------------------------------------------------------------
# SymbolTable
# ---------------------------------------------------------------------------


@dataclass
class SymbolTable:
    """A stack of :class:`Scope` objects representing nested lexical scopes.

    Typical usage by the parser::

        sym_table = SymbolTable()
        sym_table.new_scope()          # global (module) scope
        sym_table.add(integer_type)
        sym_table.new_scope()          # procedure scope
        sym_table.add(local_var)
        sym_table.close_scope()        # leave procedure
        sym_table.close_scope()        # leave module

    Attributes:
        scopes: The stack of active scopes, innermost last.
    """

    scopes: list[Scope] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Scope management
    # ------------------------------------------------------------------

    def current_level(self) -> int:
        """Return the nesting depth of the innermost open scope (0-based)."""
        return len(self.scopes) - 1

    def current_scope(self) -> Scope:
        """Return the innermost open :class:`Scope`.

        Raises:
            IndexError: If no scope is currently open.
        """
        if not self.scopes:
            raise IndexError("No open scope")
        return self.scopes[-1]

    def new_scope(self) -> None:
        """Open a new, empty scope and push it onto the stack.

        The new scope's level equals ``len(scopes)`` before the push.
        """
        level = len(self.scopes)
        logger.debug(f"Opening scope at level {level}")
        self.scopes.append(Scope(level=level))

    def close_scope(self) -> None:
        """Pop the innermost scope off the stack.

        All symbols defined in the closed scope are discarded (they go out
        of reach after the corresponding procedure or module body ends).

        Raises:
            IndexError: If no scope is currently open.
        """
        if not self.scopes:
            raise IndexError("No scope to close")
        level = self.current_level()
        logger.debug(f"Closing scope at level {level} — symbols defined here:")
        for sym in self.scopes[-1].symbols.values():
            logger.debug(f"  {sym}")
        self.scopes.pop()

    # ------------------------------------------------------------------
    # Symbol registration and lookup
    # ------------------------------------------------------------------

    def add(self, symbol: Symbol) -> None:
        """Add *symbol* to the innermost open scope.

        Delegates to :meth:`Scope.add` and propagates :class:`KeyError` on
        duplicate names.

        Args:
            symbol: The symbol to register.

        Raises:
            KeyError:   If *symbol.name* is already declared in the current scope.
            IndexError: If no scope is currently open.
        """
        self.current_scope().add(symbol)

    def find(
        self,
        name: str,
        class_: type = Symbol,
        min_level: int = 0,
        max_level: int | None = None,
    ) -> Symbol | None:
        """Search for *name* from the innermost scope outward.

        Args:
            name:      The identifier to look up.
            class_:    Restrict the search to symbols that are instances of
                       this class.  Defaults to :class:`Symbol` (any symbol).
            min_level: Do not search scopes whose level is below this value.
                       Useful to restrict lookup to a specific scope depth.
            max_level: Do not search scopes whose level is at or above this
                       value (exclusive upper bound).  ``None`` means no upper
                       limit.

        Returns:
            The innermost matching :class:`Symbol`, or ``None`` if no match
            is found within the specified level range.
        """
        slice_ = self.scopes[min_level:max_level]
        for scope in reversed(slice_):
            s = scope.find(name, class_)
            if s is not None:
                return s
        logger.debug(f"Symbol '{name}' not found in any scope")
        return None
