# SPDX-FileCopyrightText: 2026 Jeremy Prin <prin.jeremy@protonmail.ch>
#
# SPDX-License-Identifier: MIT

"""
Oberon-0 scanner (lexer).

The :class:`Scanner` reads an Oberon-0 source file character by character
and produces a stream of :class:`~oberon0_compiler.token.Token` values.
Use :meth:`Scanner.open` to attach a text stream, then call
:meth:`Scanner.get_next_symbol` repeatedly until :attr:`Scanner.eof` is
``True`` or :attr:`Scanner.sym` equals :attr:`~oberon0_compiler.token.Token.EOF`.
"""

import io
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar, final

from loguru import logger
from typing_extensions import override

from .token import Token


@final
@dataclass
class Position:
    """Source-code position (file, line, column)."""

    file_name: str
    line_no: int
    col_no: int


@final
class ScannerError(Exception):
    """Exception raised when the scanner encounters an unrecoverable error.

    Attributes:
        position: The :class:`Position` in the source where the error occurred.
    """

    def __init__(self, message: str, position: Position) -> None:
        super().__init__(message)
        self.position = position

    @override
    def __str__(self) -> str:
        p = self.position
        return (
            f"{self.args[0]} (File {p.file_name}, Line {p.line_no}, Column {p.col_no})"
        )


@final
@dataclass
class Scanner:
    """Oberon-0 lexical scanner.

    Typical usage::

        scanner = Scanner()
        with open("hello.mod") as f:
            scanner.open(f)
        while not scanner.eof:
            scanner.get_next_symbol()
            print(scanner.sym, scanner.value)

    Attributes:
        eof:       ``True`` once the end of the source stream has been reached.
        sym:       The most recently scanned :class:`~oberon0_compiler.token.Token`.
        value:     The raw text of the last identifier or number token.
        file_name: Path of the source file, or ``None`` for in-memory streams.
        line_no:   Current line number (1-based).
        col_no:    Current column number (1-based).
    """

    eof: bool = False
    sym: Enum | None = None
    value: str = ""
    file_name: Path | None = None
    line_no: int = 0
    col_no: int = 0

    _ch: str = ""
    _text: io.TextIOBase | None = None
    _text_line: str = ""

    # Maps keyword text -> Token  (e.g. "IF" -> Token.IF)
    _keyword: ClassVar[dict[str, Token]] = {
        str(i): i for i in Token if str(i).isupper()
    }

    # Maps symbol text -> Token  (e.g. "*" -> Token.TIMES)
    _symbol: ClassVar[dict[str, Token]] = {
        str(i): i for i in Token if not str(i).isupper() and not str(i).islower()
    }

    def open(self, text: io.TextIOBase) -> None:
        """Attach a text stream and read the first character.

        Args:
            text: An open, readable text stream (e.g. :class:`io.StringIO` or
                  a file opened with ``open(..., "r")``).
        """
        self._text = text
        if isinstance(text, io.TextIOWrapper):
            self.file_name = Path(text.name)
        else:
            self.file_name = None

        self.get_next_char()

    def position(self) -> Position:
        """Return the current scanner position.

        Returns:
            A :class:`Position` snapshot of the current file, line and column.
        """
        return Position(
            file_name=str(self.file_name) if self.file_name else "",
            line_no=self.line_no,
            col_no=self.col_no,
        )

    def skip_space(self) -> None:
        """Advance past any whitespace characters in the source stream."""
        while self._ch.isspace():
            self.get_next_char()

    def skip_comment(self) -> None:
        """Skip an Oberon-0 block comment, supporting arbitrary nesting.

        The method must be called **after** the opening ``(*`` has been
        consumed.  It advances the stream until the matching ``*)`` is found,
        then consumes the ``*)`` so that :attr:`_ch` holds the first character
        after the comment on return.

        Raises:
            ScannerError: If the end of file is reached before the comment is
                closed.
        """
        while True:
            self.get_next_char()
            if self.eof:
                raise ScannerError("Unterminated comment", self.position())
            if self._ch == "(":
                self.get_next_char()
                if self._ch == "*":
                    self.get_next_char()
                    self.skip_comment()
            if self._ch == "*":
                self.get_next_char()
                if self._ch == ")":
                    self.get_next_char()
                    return

    def get_next_char(self) -> None:
        """Read the next character from the source stream into :attr:`_ch`.

        When the stream is exhausted :attr:`eof` is set to ``True`` and
        :attr:`_ch` is set to the empty string.
        """
        assert self._text is not None
        while not self.eof and self._text_line == "":
            self._text_line = self._text.readline()
            self.line_no += 1
            self.col_no = 0
            if self._text_line == "":
                self.eof = True
                break
            self._text_line = self._text_line.rstrip("\r")
        if self.eof:
            self._ch = ""
        else:
            assert self._text_line != ""
            self._ch = self._text_line[0]
            self._text_line = self._text_line[1:]
            self.col_no += 1

    def get_next_symbol(self) -> None:  # noqa: C901
        """Scan the next token from the source stream.

        After this method returns the following attributes are updated:

        * :attr:`sym` -- the :class:`~oberon0_compiler.token.Token` that was
          recognised.
        * :attr:`value` -- the raw text for ``IDENT`` and ``NUMBER`` tokens,
          or the operator text for multi-character operators such as ``":="``
          and ``"<="``; empty string for single-character punctuation and
          keywords.
        * :attr:`eof` -- set to ``True`` once the end of the source has been
          reached.

        Whitespace and nested block comments (``(* ... *)``) are silently
        discarded.

        Raises:
            ScannerError: Propagated from :meth:`skip_comment` when an
                unterminated comment is detected.
        """
        # --- Skip whitespace and block comments ----------------------------
        self.skip_space()

        # A "(" may open a comment (* ... *) or be a plain LPAREN.
        # We peek at the next character to disambiguate.  If it turns out
        # to be a plain LPAREN we return immediately; the peeked character
        # stays in self._ch for the next call.
        while self._ch == "(" and not self.eof:
            self.get_next_char()  # peek
            if self._ch == "*":
                # It is a comment: skip it, then resume whitespace skipping.
                self.get_next_char()  # consume "*"
                self.skip_comment()  # advance past "*)"
                self.skip_space()
            else:
                # Plain left parenthesis.
                self.sym = Token.LPAREN
                self.value = "("
                logger.debug(f"Symbol: {self.sym!r}, value: {self.value!r}")
                return

        # --- End of file ---------------------------------------------------
        if self.eof:
            self.sym = Token.EOF
            self.value = ""
            logger.debug("Symbol: EOF")
            return

        ch = self._ch  # save current character before advancing

        # --- Integer literal -----------------------------------------------
        if ch.isdigit():
            self.value = ""
            while not self.eof and self._ch.isdigit():
                self.value += self._ch
                self.get_next_char()
            self.sym = Token.NUMBER

        # --- Identifier or keyword -----------------------------------------
        elif ch.isalpha():
            self.value = ""
            while not self.eof and self._ch.isalnum():
                self.value += self._ch
                self.get_next_char()
            if self.value in self._keyword:
                self.sym = self._keyword[self.value]
            else:
                self.sym = Token.IDENT

        # --- ":=" (BECOMES) or ":" (COLON) ---------------------------------
        elif ch == ":":
            self.get_next_char()
            if self._ch == "=":
                self.value = ":="
                self.sym = Token.BECOMES
                self.get_next_char()
            else:
                self.value = ":"
                self.sym = Token.COLON

        # --- "<=" (LEQ) or "<" (LSS) ---------------------------------------
        elif ch == "<":
            self.get_next_char()
            if self._ch == "=":
                self.value = "<="
                self.sym = Token.LEQ
                self.get_next_char()
            else:
                self.value = "<"
                self.sym = Token.LSS

        # --- ">=" (GEQ) or ">" (GTR) ---------------------------------------
        elif ch == ">":
            self.get_next_char()
            if self._ch == "=":
                self.value = ">="
                self.sym = Token.GEQ
                self.get_next_char()
            else:
                self.value = ">"
                self.sym = Token.GTR

        # --- Single-character symbols --------------------------------------
        elif ch in self._symbol:
            self.value = ch
            self.sym = self._symbol[ch]
            self.get_next_char()

        # --- Unknown character ---------------------------------------------
        else:
            self.value = ch
            self.sym = Token.OTHER
            self.get_next_char()

        logger.debug(f"Symbol: {self.sym!r}, value: {self.value!r}")
