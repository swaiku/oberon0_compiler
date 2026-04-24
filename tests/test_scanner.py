# SPDX-FileCopyrightText: 2026 Jeremy Prin <prin.jeremy@protonmail.ch>
#
# SPDX-License-Identifier: MIT

"""
Unit tests for the Oberon-0 scanner (:mod:`oberon0_compiler.scanner`).

Each test feeds a small Oberon-0 source string into the scanner via
:class:`io.StringIO` and verifies that the correct sequence of tokens
(and, where applicable, token values) is produced.
"""

import io
import typing

import pytest

from oberon0_compiler.scanner import Scanner, ScannerError
from oberon0_compiler.token import Token

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_scanner(src: str) -> Scanner:
    """Create a :class:`Scanner` pre-loaded with *src*."""
    scanner = Scanner()
    scanner.open(io.StringIO(src))
    return scanner


def next_sym(scanner: Scanner) -> Token:
    """Advance the scanner and return the new symbol as a :class:`Token`."""
    scanner.get_next_symbol()
    return typing.cast(Token, scanner.sym)


# ---------------------------------------------------------------------------
# Tests provided by the practical-work specification
# ---------------------------------------------------------------------------


def test_assignment() -> None:
    """Tokens in a simple VAR assignment statement."""
    src = "VAR i := 12;"
    scanner = make_scanner(src)

    scanner.get_next_symbol()
    assert scanner.sym == Token.VAR

    scanner.get_next_symbol()
    assert typing.cast(Token, scanner.sym) == Token.IDENT
    assert scanner.value == "i"

    scanner.get_next_symbol()
    assert typing.cast(Token, scanner.sym) == Token.BECOMES

    scanner.get_next_symbol()
    assert typing.cast(Token, scanner.sym) == Token.NUMBER
    assert scanner.value == "12"

    scanner.get_next_symbol()
    assert typing.cast(Token, scanner.sym) == Token.SEMICOLON


def test_compare_leq() -> None:
    """'<=' operator is scanned as LEQ, not LSS followed by EQL."""
    src = "i <= -5"
    scanner = make_scanner(src)

    scanner.get_next_symbol()
    assert scanner.sym == Token.IDENT
    assert scanner.value == "i"

    scanner.get_next_symbol()
    assert typing.cast(Token, scanner.sym) == Token.LEQ
    assert scanner.value == "<="

    scanner.get_next_symbol()
    assert typing.cast(Token, scanner.sym) == Token.MINUS

    scanner.get_next_symbol()
    assert typing.cast(Token, scanner.sym) == Token.NUMBER
    assert scanner.value == "5"


def test_compare_less() -> None:
    """Bare '<' is scanned as LSS."""
    src = "i < 0"
    scanner = make_scanner(src)

    scanner.get_next_symbol()
    assert scanner.sym == Token.IDENT
    assert scanner.value == "i"

    scanner.get_next_symbol()
    assert typing.cast(Token, scanner.sym) == Token.LSS
    assert scanner.value == "<"

    scanner.get_next_symbol()
    assert typing.cast(Token, scanner.sym) == Token.NUMBER
    assert scanner.value == "0"


# ---------------------------------------------------------------------------
# Additional tests
# ---------------------------------------------------------------------------


def test_eof() -> None:
    """An empty source produces a single EOF token."""
    scanner = make_scanner("")
    assert next_sym(scanner) == Token.EOF
    assert scanner.eof


def test_keywords() -> None:
    """All Oberon-0 reserved words are returned as their keyword tokens."""
    keywords = [
        ("IF", Token.IF),
        ("THEN", Token.THEN),
        ("ELSE", Token.ELSE),
        ("ELSIF", Token.ELSIF),
        ("END", Token.END),
        ("WHILE", Token.WHILE),
        ("DO", Token.DO),
        ("REPEAT", Token.REPEAT),
        ("UNTIL", Token.UNTIL),
        ("VAR", Token.VAR),
        ("CONST", Token.CONST),
        ("PROCEDURE", Token.PROCEDURE),
        ("BEGIN", Token.BEGIN),
        ("MODULE", Token.MODULE),
        ("DIV", Token.DIV),
        ("MOD", Token.MOD),
        ("OR", Token.OR),
        ("OF", Token.OF),
    ]
    for text, expected in keywords:
        scanner = make_scanner(text)
        assert next_sym(scanner) == expected, f"keyword {text!r} was not recognised"


def test_identifier_vs_keyword_prefix() -> None:
    """An identifier that starts with a keyword is not treated as a keyword."""
    scanner = make_scanner("IFx")
    assert next_sym(scanner) == Token.IDENT
    assert scanner.value == "IFx"


def test_compare_geq() -> None:
    """'>=' is scanned as GEQ."""
    scanner = make_scanner("x >= 0")
    assert next_sym(scanner) == Token.IDENT
    assert next_sym(scanner) == Token.GEQ
    assert scanner.value == ">="
    assert next_sym(scanner) == Token.NUMBER


def test_compare_gtr() -> None:
    """Bare '>' is scanned as GTR."""
    scanner = make_scanner("x > 0")
    assert next_sym(scanner) == Token.IDENT
    assert next_sym(scanner) == Token.GTR
    assert scanner.value == ">"
    assert next_sym(scanner) == Token.NUMBER


def test_becomes_vs_colon() -> None:
    """':=' is BECOMES; a lone ':' is COLON."""
    scanner = make_scanner(":= :")
    assert next_sym(scanner) == Token.BECOMES
    assert scanner.value == ":="
    assert next_sym(scanner) == Token.COLON
    assert scanner.value == ":"


def test_single_char_symbols() -> None:
    """Single-character punctuation tokens are recognised correctly."""
    cases = [
        ("*", Token.TIMES),
        ("&", Token.AND),
        ("+", Token.PLUS),
        ("-", Token.MINUS),
        ("=", Token.EQL),
        ("#", Token.NEQ),
        (".", Token.PERIOD),
        ("~", Token.NOT),
        (",", Token.COMMA),
        (")", Token.RPAREN),
        (";", Token.SEMICOLON),
    ]
    for text, expected in cases:
        scanner = make_scanner(text)
        assert next_sym(scanner) == expected, f"symbol {text!r} was not recognised"


def test_comment_skipped() -> None:
    """Block comments are silently ignored."""
    scanner = make_scanner("(* this is a comment *) 42")
    assert next_sym(scanner) == Token.NUMBER
    assert scanner.value == "42"


def test_nested_comment() -> None:
    """Nested block comments are handled correctly."""
    scanner = make_scanner("(* outer (* inner *) still outer *) END")
    assert next_sym(scanner) == Token.END


def test_unterminated_comment() -> None:
    """An unterminated block comment raises :class:`ScannerError`."""
    scanner = make_scanner("(* oops")
    with pytest.raises(ScannerError):
        scanner.get_next_symbol()


def test_lparen_not_comment() -> None:
    """'(' followed by a non-'*' character is a plain LPAREN."""
    scanner = make_scanner("(x)")
    assert next_sym(scanner) == Token.LPAREN
    assert next_sym(scanner) == Token.IDENT
    assert scanner.value == "x"
    assert next_sym(scanner) == Token.RPAREN


def test_multiline_input() -> None:
    """Tokens spread across multiple lines are scanned correctly."""
    src = "MODULE\nFoo\n;\n"
    scanner = make_scanner(src)
    assert next_sym(scanner) == Token.MODULE
    assert next_sym(scanner) == Token.IDENT
    assert scanner.value == "Foo"
    assert next_sym(scanner) == Token.SEMICOLON


def test_number_followed_by_period() -> None:
    """A number directly followed by '.' yields NUMBER then PERIOD."""
    scanner = make_scanner("42.")
    assert next_sym(scanner) == Token.NUMBER
    assert scanner.value == "42"
    assert next_sym(scanner) == Token.PERIOD


def test_unknown_character() -> None:
    """An unrecognised character produces Token.OTHER."""
    scanner = make_scanner("@")
    assert next_sym(scanner) == Token.OTHER
