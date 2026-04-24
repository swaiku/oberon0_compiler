# SPDX-FileCopyrightText: 2026 Jeremy Prin <prin.jeremy@protonmail.ch>
#
# SPDX-License-Identifier: MIT

"""
Oberon-0 token definitions.

Each member of the :class:`Token` enumeration represents a lexical unit
recognised by the Oberon-0 scanner.  The string value of every member is
the canonical textual representation of that token (e.g. ``"*"`` for
:attr:`Token.TIMES` or ``"IF"`` for :attr:`Token.IF`).
"""

from enum import Enum
from typing import override


class Token(str, Enum):
    """Enumeration of all tokens produced by the Oberon-0 scanner."""

    NULL = "null"
    TIMES = "*"
    DIV = "DIV"
    MOD = "MOD"
    AND = "&"
    PLUS = "+"
    MINUS = "-"
    OR = "OR"
    EQL = "="
    NEQ = "#"
    LSS = "<"
    LEQ = "<="
    GTR = ">"
    GEQ = ">="
    PERIOD = "."
    NOT = "~"
    LPAREN = "("
    IDENT = "identifier"
    NUMBER = "number"
    IF = "IF"
    WHILE = "WHILE"
    REPEAT = "REPEAT"
    COMMA = ","
    COLON = ":"
    BECOMES = ":="
    RPAREN = ")"
    THEN = "THEN"
    OF = "OF"
    DO = "DO"
    SEMICOLON = ";"
    END = "END"
    ELSE = "ELSE"
    ELSIF = "ELSIF"
    UNTIL = "UNTIL"
    CONST = "CONST"
    VAR = "VAR"
    PROCEDURE = "PROCEDURE"
    BEGIN = "BEGIN"
    MODULE = "MODULE"
    EOF = "eof"
    OTHER = "unknown"

    @override
    def __str__(self) -> str:
        return self.value
