# SPDX-FileCopyrightText: 2026 Jeremy Prin <prin.jeremy@protonmail.ch>
#
# SPDX-License-Identifier: MIT

"""
Recursive-descent parser for Oberon-0.
=======================================

This module implements a hand-written recursive-descent parser for the
simplified Oberon-0 grammar defined in TP05.  It consumes the token stream
produced by :class:`~oberon0_compiler.scanner.Scanner` and builds an
Abstract Syntax Tree (AST) whose node types are defined in
:mod:`oberon0_compiler.ast`.

Grammar (simplified, from the TP05 specification)
--------------------------------------------------

::

    ident            = letter {letter | digit} .
    integer          = digit {digit} .
    number           = integer .
    factor           = ident [ActualParameters] | number | "(" expression ")" .
    term             = factor {("*" | "DIV" | "MOD") factor} .
    SimpleExpression = ["+"|"-"] term {("+"|"-") term} .
    expression       = SimpleExpression .
    assignment       = ident ":=" expression .
    ActualParameters = "(" [expression {"," expression}] ")" .
    ProcedureCall    = ident [ActualParameters] .
    statement        = [assignment | ProcedureCall] .
    StatementSequence= statement {";" statement} .
    IdentList        = ident {"," ident} .
    type             = ident .
    ProcedureHeading = "PROCEDURE" ident ["*"] .
    ProcedureBody    = declarations ["BEGIN" StatementSequence] "END" ident .
    ProcedureDeclaration = ProcedureHeading ";" ProcedureBody .
    declarations     = ["VAR" {IdentList ":" type ";"}]
                       {ProcedureDeclaration ";"} .
    module           = "MODULE" ident ";"
                       declarations
                       "END" ident "." .

Scanner / token conventions
----------------------------

The parser follows the Wirth-style lookahead convention:

* When a parsing method is **entered**, ``scanner.sym`` holds the **first**
  token of the production being parsed (the current lookahead).
* When a parsing method **returns**, ``scanner.sym`` holds the **first**
  token *after* the production that was just consumed (the next lookahead).

Every call to ``scanner.get_next_symbol()`` advances the scanner by exactly
one token.

Symbol table
------------

The parser uses a :class:`~oberon0_compiler.sym_table.SymbolTable` that is
populated before parsing begins with the built-in types
(:mod:`oberon0_compiler.types`) and system calls
(:mod:`oberon0_compiler.systemcalls`).  Identifiers are looked up and
registered as the parser proceeds through declarations.

Variable offsets
----------------

Variable offsets within a scope are assigned sequentially.  A local counter
starts at 0 and is incremented by ``type_.size`` bytes for each variable
declared in the VAR block.  Global variables (module-level VAR) receive
:class:`~oberon0_compiler.sym_table.GlobalVariable` entries; local variables
(inside a procedure) receive
:class:`~oberon0_compiler.sym_table.LocalVariable` entries.

Error handling
--------------

All parsing errors raise :class:`ParserError`, which embeds the source
:class:`~oberon0_compiler.scanner.Position` so that the caller can display
a meaningful ``File / Line / Column`` diagnostic.

Usage example::

    import io
    from oberon0_compiler.scanner import Scanner
    from oberon0_compiler.parser import Parser

    scanner = Scanner()
    scanner.open(io.StringIO("MODULE M; END M."))
    parser = Parser(scanner=scanner)
    module_node = parser.parse()
    print(module_node)
"""

from dataclasses import dataclass, field
from typing import cast, final, no_type_check, override

from loguru import logger

from . import ast, systemcalls, types
from . import sym_table as SYM
from .scanner import Position, Scanner
from .token import Token

# ---------------------------------------------------------------------------
# Parser error
# ---------------------------------------------------------------------------


@final
class ParserError(Exception):
    """Exception raised when the parser encounters a syntax or semantic error.

    Attributes:
        position: The source location where the error was detected.
    """

    def __init__(self, message: str, position: Position) -> None:
        super().__init__(message)
        self.position = position

    @override
    def __str__(self) -> str:
        p = self.position
        return (
            f"{self.args[0]} "
            f"(File {p.file_name!r}, Line {p.line_no}, Column {p.col_no})"
        )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


@dataclass
class Parser:
    """Recursive-descent parser for the simplified Oberon-0 grammar.

    The parser is stateful: it owns both the :class:`~scanner.Scanner` and the
    :class:`~sym_table.SymbolTable`.  Create one instance per source file and
    call :meth:`parse` exactly once.

    Attributes:
        scanner:   The lexical scanner that supplies the token stream.
        sym_table: The symbol table populated during parsing.  Pre-loaded
                   with built-in types and system calls by :meth:`parse`.

    Example::

        parser = Parser(scanner=scanner)
        module_node = parser.parse()
        print(module_node)          # pretty-print the reconstructed source
    """

    scanner: Scanner
    sym_table: SYM.SymbolTable = field(default_factory=SYM.SymbolTable)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @no_type_check
    def _check_sym(self, expected: Token) -> None:
        """Assert that the current lookahead equals *expected*.

        This is a *non-advancing* check: the scanner position is not changed.
        Call ``scanner.get_next_symbol()`` afterwards to consume the token.

        Args:
            expected: The :class:`~token.Token` that must be present.

        Raises:
            ParserError: When ``scanner.sym != expected``.
        """
        if self.scanner.sym != expected:
            raise ParserError(
                f"Expected '{expected}', but got '{self.scanner.sym}'",
                self.scanner.position(),
            )

    # Kept for backward compatibility with code that calls check_sym directly.
    check_sym = _check_sym

    def _expect(self, expected: Token) -> None:
        """Assert the current lookahead equals *expected*, then advance.

        Convenience wrapper around :meth:`_check_sym` +
        ``scanner.get_next_symbol()``.

        Args:
            expected: The token that must be present at the current position.

        Raises:
            ParserError: When ``scanner.sym != expected``.
        """
        self._check_sym(expected)
        self.scanner.get_next_symbol()

    # ------------------------------------------------------------------
    # Expression parsing
    # ------------------------------------------------------------------

    def _actual_parameters(self) -> list[ast.Expression]:
        """Parse an optional actual-parameter list and return the arguments.

        Called when ``scanner.sym == Token.LPAREN``.  On return the scanner
        is positioned on the first token **after** the closing ``)``.

        Grammar rule::

            ActualParameters = "(" [expression {"," expression}] ")" .

        Returns:
            A (possibly empty) list of parsed :class:`~ast.Expression` nodes,
            one per actual argument.

        Raises:
            ParserError: On any unexpected token.
        """
        logger.debug("parsing ActualParameters")
        # Consume the opening '('
        self._expect(Token.LPAREN)

        args: list[ast.Expression] = []

        if self.scanner.sym != Token.RPAREN:
            # Parse the first argument.
            args.append(self.expression())
            # Parse any additional comma-separated arguments.
            while self.scanner.sym == Token.COMMA:
                self.scanner.get_next_symbol()  # consume ','
                args.append(self.expression())

        # Consume the closing ')'
        self._expect(Token.RPAREN)
        return args

    def factor(self) -> ast.Factor:
        """Parse a single *factor* and return its AST node.

        On entry ``scanner.sym`` is the first token of the factor.
        On return ``scanner.sym`` is the first token **after** the factor.

        Grammar rule::

            factor = ident [ActualParameters] | number | "(" expression ")" .

        The parser looks up every identifier in the symbol table:

        * If the identifier resolves to a :class:`~sym_table.Variable` and no
          actual parameters follow, an :class:`~ast.Ident` node is returned.
        * If the identifier resolves to a :class:`~sym_table.SystemCall` or
          :class:`~sym_table.ProcedureDefinition`, a
          :class:`~ast.ProcedureCallFactor` node is returned (with or without
          arguments).
        * Any other symbol type (e.g. a :class:`~sym_table.Type`) in factor
          position is a parse error.

        Returns:
            A concrete :class:`~ast.Factor` sub-class instance.

        Raises:
            ParserError: When the identifier is undeclared, when an identifier
                         of the wrong class appears, or when no valid factor
                         start token is found.
        """
        logger.debug("parsing factor")
        pos = self.scanner.position()

        # ident [ActualParameters]
        if self.scanner.sym == Token.IDENT:
            name = self.scanner.value
            self.scanner.get_next_symbol()  # consume the identifier

            symbol = self.sym_table.find(name)
            if symbol is None:
                raise ParserError(f"Undeclared identifier '{name}'", pos)

            if isinstance(symbol, SYM.Variable):
                # Simple variable reference.
                return ast.Ident(position=pos, symbol=symbol)

            if isinstance(symbol, (SYM.SystemCall, SYM.ProcedureDefinition)):
                # Callable used as a value (e.g. eot()).
                args: list[ast.Expression] = []
                if self.scanner.sym == Token.LPAREN:
                    args = self._actual_parameters()
                return ast.ProcedureCallFactor(position=pos, symbol=symbol, args=args)

            raise ParserError(
                f"'{name}' (type {type(symbol).__name__}) \
                cannot appear in an expression",
                pos,
            )

        # number
        if self.scanner.sym == Token.NUMBER:
            value = int(self.scanner.value)
            self.scanner.get_next_symbol()  # consume the number
            return ast.Number(position=pos, value=value)

        # "(" expression ")"
        if self.scanner.sym == Token.LPAREN:
            self.scanner.get_next_symbol()  # consume '('
            expr = self.expression()
            self._expect(Token.RPAREN)  # consume ')'
            return ast.ParenExpression(position=pos, expression=expr)

        raise ParserError(
            f"Expected a factor (identifier, number, or '('), \
            but got '{self.scanner.sym}'",
            pos,
        )

    def term(self) -> ast.Term:
        """Parse a *term* (factors joined by multiplicative operators).

        On entry ``scanner.sym`` is the first token of the term.
        On return ``scanner.sym`` is the first token **after** the term.

        Grammar rule::

            term = factor {("*" | "DIV" | "MOD") factor} .

        Returns:
            A :class:`~ast.Term` node whose :attr:`~ast.Term.mulop_factors`
            list contains zero or more ``(operator_string, factor)`` pairs.

        Raises:
            ParserError: Propagated from :meth:`factor`.
        """
        logger.debug("parsing term")
        pos = self.scanner.position()

        leading = self.factor()
        mulop_factors: list[tuple[str, ast.Factor]] = []

        while self.scanner.sym in (Token.TIMES, Token.DIV, Token.MOD):
            op = str(self.scanner.sym)  # "*", "DIV", or "MOD"
            self.scanner.get_next_symbol()  # consume the operator
            mulop_factors.append((op, self.factor()))

        return ast.Term(position=pos, factor=leading, mulop_factors=mulop_factors)

    def simple_expression(self) -> ast.SimpleExpression:
        """Parse a *SimpleExpression* (terms joined by additive operators).

        On entry ``scanner.sym`` is the first token of the expression.
        On return ``scanner.sym`` is the first token **after** the expression.

        Grammar rule::

            SimpleExpression = ["+"|"-"] term {("+"|"-") term} .

        Returns:
            A :class:`~ast.SimpleExpression` node.  The optional unary sign
            is ``"+"`` or ``"-"`` when present, ``None`` otherwise.

        Raises:
            ParserError: Propagated from :meth:`term`.
        """
        logger.debug("parsing SimpleExpression")
        pos = self.scanner.position()

        # Optional leading sign.
        sign: str | None = None
        if self.scanner.sym in (Token.PLUS, Token.MINUS):
            sign = str(self.scanner.sym)
            self.scanner.get_next_symbol()  # consume '+' or '-'

        leading_term = self.term()
        addop_terms: list[tuple[str, ast.Term]] = []

        while self.scanner.sym in (Token.PLUS, Token.MINUS):
            op = str(self.scanner.sym)  # "+" or "-"
            self.scanner.get_next_symbol()  # consume the operator
            addop_terms.append((op, self.term()))

        return ast.SimpleExpression(
            position=pos,
            sign=sign,
            term=leading_term,
            addop_terms=addop_terms,
        )

    def expression(self) -> ast.Expression:
        """Parse an *expression*.

        In the simplified TP05 grammar ``expression = SimpleExpression``, so
        this method simply delegates to :meth:`simple_expression`.

        On entry ``scanner.sym`` is the first token of the expression.
        On return ``scanner.sym`` is the first token **after** the expression.

        Grammar rule::

            expression = SimpleExpression .

        Returns:
            A :class:`~ast.SimpleExpression` node (the sole concrete
            :class:`~ast.Expression` sub-type in this grammar).

        Raises:
            ParserError: Propagated from :meth:`simple_expression`.
        """
        logger.debug("parsing expression")
        return self.simple_expression()

    # ------------------------------------------------------------------
    # Statement parsing
    # ------------------------------------------------------------------

    def statement(self) -> ast.Statement | None:
        """Parse one (possibly empty) *statement*.

        On entry ``scanner.sym`` is the first token of the statement, which
        may not be an identifier (empty statement case).
        On return ``scanner.sym`` is the first token **after** the statement.

        Grammar rule::

            statement = [assignment | ProcedureCall] .

        Both ``assignment`` and ``ProcedureCall`` begin with an identifier.
        A single token of lookahead after the identifier disambiguates the
        two alternatives:

        * ``:=`` -> :class:`~ast.Assignment`
        * anything else -> :class:`~ast.ProcedureCallStatement` (with or
          without actual parameters)

        An empty statement (``scanner.sym`` is not an identifier) returns
        ``None``.  Empty statements arise from a trailing ``;`` before
        ``END``.

        Returns:
            A :class:`~ast.Statement` sub-class instance, or ``None`` for an
            empty statement.

        Raises:
            ParserError: When the identifier is undeclared, when a
                         non-callable symbol appears in call position, or when
                         a variable appears in call position without ``:=``.
        """
        logger.debug("parsing statement")

        if self.scanner.sym != Token.IDENT:
            # Empty statement: return without consuming any token.
            return None

        pos = self.scanner.position()
        name = self.scanner.value
        self.scanner.get_next_symbol()  # consume the identifier

        # --- Assignment ---------------------------------------------------
        if self.scanner.sym == Token.BECOMES:
            self.scanner.get_next_symbol()  # consume ':='

            symbol = self.sym_table.find(name, SYM.Variable)
            if symbol is None:
                # Check whether the name exists at all (better error message).
                any_sym = self.sym_table.find(name)
                if any_sym is None:
                    raise ParserError(f"Undeclared identifier '{name}'", pos)
                raise ParserError(
                    f"'{name}' is not a variable and cannot appear \
                    on the left-hand side of an assignment",
                    pos,
                )

            expr = self.expression()
            return ast.Assignment(position=pos, symbol=symbol, expression=expr)

        # --- Procedure call -----------------------------------------------
        symbol = self.sym_table.find(name)
        if symbol is None:
            raise ParserError(f"Undeclared identifier '{name}'", pos)

        if not isinstance(symbol, (SYM.SystemCall, SYM.ProcedureDefinition)):
            raise ParserError(
                f"'{name}' (type {type(symbol).__name__}) is not callable; \
                did you mean ':=' for an assignment?",
                pos,
            )

        args: list[ast.Expression] = []
        if self.scanner.sym == Token.LPAREN:
            args = self._actual_parameters()

        return ast.ProcedureCallStatement(position=pos, symbol=symbol, args=args)

    def statement_sequence(self) -> ast.StatementSequence:
        """Parse a *StatementSequence* (statements separated by semicolons).

        On entry ``scanner.sym`` is the first token of the first statement
        (or the token that follows ``BEGIN``).
        On return ``scanner.sym`` is the first token **after** the sequence
        (typically ``END``).

        Grammar rule::

            StatementSequence = statement {";" statement} .

        Empty statements (``None`` returns from :meth:`statement`) are
        silently discarded so that the resulting
        :class:`~ast.StatementSequence` contains only non-null statements.

        Returns:
            A :class:`~ast.StatementSequence` node.

        Raises:
            ParserError: Propagated from :meth:`statement`.
        """
        logger.debug("parsing StatementSequence")
        pos = self.scanner.position()
        statements: list[ast.Statement] = []

        s = self.statement()
        if s is not None:
            statements.append(s)

        while self.scanner.sym == Token.SEMICOLON:
            self.scanner.get_next_symbol()  # consume ';'
            s = self.statement()
            if s is not None:
                statements.append(s)

        return ast.StatementSequence(position=pos, statements=statements)

    # ------------------------------------------------------------------
    # Declaration parsing
    # ------------------------------------------------------------------

    def _ident_list(self) -> list[str]:
        """Parse a comma-separated list of identifiers.

        On entry ``scanner.sym == Token.IDENT``.
        On return ``scanner.sym`` is the token **after** the last identifier
        in the list (typically ``:``).

        Grammar rule::

            IdentList = ident {"," ident} .

        Returns:
            An ordered list of identifier strings.

        Raises:
            ParserError: When a token other than an identifier is found after
                         a comma.
        """
        logger.debug("parsing IdentList")
        self._check_sym(Token.IDENT)
        names: list[str] = [self.scanner.value]
        self.scanner.get_next_symbol()  # consume first identifier

        while self.scanner.sym == Token.COMMA:
            self.scanner.get_next_symbol()  # consume ','
            self._check_sym(Token.IDENT)
            names.append(self.scanner.value)
            self.scanner.get_next_symbol()  # consume identifier

        return names

    def _type(self) -> SYM.Type:
        """Parse a type name and return the corresponding :class:`~sym_table.Type`.

        On entry ``scanner.sym == Token.IDENT`` (the type name).
        On return ``scanner.sym`` is the token **after** the type identifier.

        Grammar rule::

            type = ident .

        The identifier is looked up in the symbol table.  Only symbols of
        class :class:`~sym_table.Type` are accepted.

        Returns:
            The resolved :class:`~sym_table.Type` instance.

        Raises:
            ParserError: When the identifier is not declared or does not refer
                         to a type.
        """
        logger.debug("parsing type")
        pos = self.scanner.position()
        self._check_sym(Token.IDENT)
        name = self.scanner.value
        self.scanner.get_next_symbol()  # consume the type identifier

        sym = self.sym_table.find(name, SYM.Type)
        if sym is None:
            raise ParserError(
                f"'{name}' is not a known type",
                pos,
            )
        # sym_table.find(name, SYM.Type) only returns SYM.Type instances;
        # the cast makes this explicit for static type checkers.
        return cast(SYM.Type, sym)

    def declarations(self, global_: bool = False) -> ast.Declarations:
        """Parse the declarations section of a module or procedure body.

        On entry ``scanner.sym`` is the first token after the opening
        semicolon of the module/procedure header (i.e. the first token that
        could start a declaration, or ``BEGIN`` / ``END`` if there are none).
        On return ``scanner.sym`` is ``BEGIN`` or ``END`` (the token that
        terminates the declarations section).

        Grammar rule::

            declarations =
                ["VAR" {IdentList ":" type ";"}]
                {ProcedureDeclaration ";"} .

        Variable offsets are assigned sequentially starting from 0.  Each
        variable consumes ``type_.size`` bytes.

        Args:
            global_: When ``True``, declared variables are added to the
                     symbol table as
                     :class:`~sym_table.GlobalVariable` (module level).
                     When ``False`` (default), they are added as
                     :class:`~sym_table.LocalVariable` (procedure level).

        Returns:
            A :class:`~ast.Declarations` node.

        Raises:
            ParserError: Propagated from :meth:`_ident_list`, :meth:`_type`,
                         or :meth:`procedure_declaration`.
            KeyError:    When a duplicate identifier is detected in the same
                         scope (propagated from
                         :meth:`~sym_table.SymbolTable.add`).
        """
        logger.debug("parsing declarations (global=%s)", global_)
        pos = self.scanner.position()
        var_decls: list[ast.VariableDeclaration] = []
        proc_decls: list[ast.ProcedureDeclaration] = []
        offset: int = 0  # running byte offset within the current scope

        # --- Optional VAR block -------------------------------------------
        if self.scanner.sym == Token.VAR:
            self.scanner.get_next_symbol()  # consume 'VAR'

            # Each iteration handles one "IdentList : type ;" group.
            while self.scanner.sym == Token.IDENT:
                decl_pos = self.scanner.position()
                names = self._ident_list()  # consume idents and ','s

                self._expect(Token.COLON)  # consume ':'

                type_sym = self._type()  # consume type identifier

                self._expect(Token.SEMICOLON)  # consume ';'

                # Register each name in the symbol table and create an AST node.
                for name in names:
                    if global_:
                        sym: SYM.LocalVariable | SYM.GlobalVariable = (
                            SYM.GlobalVariable(name=name, type_=type_sym, offset=offset)
                        )
                    else:
                        sym = SYM.LocalVariable(
                            name=name, type_=type_sym, offset=offset
                        )
                    self.sym_table.add(sym)
                    var_decls.append(
                        ast.VariableDeclaration(position=decl_pos, symbol=sym)
                    )
                    offset += type_sym.size

        # --- Zero or more procedure declarations --------------------------
        while self.scanner.sym == Token.PROCEDURE:
            p = self.procedure_declaration()  # consume through final ident
            self._expect(Token.SEMICOLON)  # consume ';' after declaration
            proc_decls.append(p)

        return ast.Declarations(
            position=pos,
            var_declarations=var_decls,
            procedure_declarations=proc_decls,
        )

    def procedure_declaration(self) -> ast.ProcedureDeclaration:
        """Parse a complete procedure declaration (heading + body).

        On entry ``scanner.sym == Token.PROCEDURE``.
        On return ``scanner.sym`` is the first token **after** the procedure's
        closing identifier (i.e. the ``;`` that follows the declaration in the
        enclosing ``declarations`` rule).

        Grammar rules::

            ProcedureHeading    = "PROCEDURE" ident ["*"] .
            ProcedureBody       = declarations
                                  ["BEGIN" StatementSequence]
                                  "END" ident .
            ProcedureDeclaration = ProcedureHeading ";" ProcedureBody .

        The procedure's :class:`~sym_table.ProcedureDefinition` symbol is
        added to the **enclosing** scope before a new scope is opened for the
        body.  This allows the procedure to call itself recursively (the name
        is visible inside the body through the outer scope).

        Args:
            (none -- called with ``scanner.sym == Token.PROCEDURE``)

        Returns:
            A :class:`~ast.ProcedureDeclaration` node.

        Raises:
            ParserError: When the identifier after ``END`` does not match the
                         procedure name, or on any other syntax error.
        """
        logger.debug("parsing ProcedureDeclaration")
        pos = self.scanner.position()

        # --- Heading ------------------------------------------------------
        self._expect(Token.PROCEDURE)  # consume 'PROCEDURE'

        self._check_sym(Token.IDENT)
        name = self.scanner.value
        self.scanner.get_next_symbol()  # consume procedure name

        exported: bool = False
        if self.scanner.sym == Token.TIMES:
            exported = True
            self.scanner.get_next_symbol()  # consume '*'

        self._expect(Token.SEMICOLON)  # consume ';'

        # Register in the enclosing scope BEFORE opening the procedure scope,
        # so that recursive calls and forward references can see the symbol.
        proc_sym = SYM.ProcedureDefinition(name=name, exported=exported, stack_size=0)
        self.sym_table.add(proc_sym)

        # --- Body ---------------------------------------------------------
        self.sym_table.new_scope()  # open the procedure's local scope

        d = self.declarations(global_=False)  # local VAR + nested procedures

        # Optional BEGIN ... StatementSequence
        body = ast.StatementSequence(position=self.scanner.position(), statements=[])
        if self.scanner.sym == Token.BEGIN:
            self.scanner.get_next_symbol()  # consume 'BEGIN'
            body = self.statement_sequence()

        # END <ident>
        self._expect(Token.END)  # consume 'END'

        self._check_sym(Token.IDENT)
        closing_name = self.scanner.value
        closing_pos = self.scanner.position()
        self.scanner.get_next_symbol()  # consume closing identifier

        if closing_name != name:
            raise ParserError(
                f"Procedure name mismatch: expected '{name}', got '{closing_name}'",
                closing_pos,
            )

        self.sym_table.close_scope()  # leave the procedure's scope

        return ast.ProcedureDeclaration(
            position=pos,
            symbol=proc_sym,
            exported=exported,
            declarations=d,
            body=body,
        )

    # ------------------------------------------------------------------
    # Module (top-level production)
    # ------------------------------------------------------------------

    def module(self) -> ast.Module:
        """Parse the top-level *module* production.

        On entry ``scanner.sym == Token.MODULE`` (already set by :meth:`parse`).
        On return ``scanner.sym == Token.EOF``.

        Grammar rule::

            module =
                "MODULE" ident ";"
                declarations
                "END" ident "." .

        The global scope is opened here, pre-populated with built-in types
        and system calls, then closed at the end of the method.

        Returns:
            The root :class:`~ast.Module` node of the AST.

        Raises:
            ParserError: When the module name after ``END`` does not match the
                         name after ``MODULE``, or on any other syntax error.
        """
        logger.debug("parsing module")
        pos = self.scanner.position()

        self._expect(Token.MODULE)  # consume 'MODULE'

        self._check_sym(Token.IDENT)
        name = self.scanner.value
        self.scanner.get_next_symbol()  # consume module name

        self._expect(Token.SEMICOLON)  # consume ';'

        # Open the global scope and populate it with built-ins.
        self.sym_table.new_scope()
        self.add_types()
        self.add_system_calls()

        # Parse all module-level declarations.
        d = self.declarations(global_=True)

        # "END" <ident> "."
        self._expect(Token.END)  # consume 'END'

        self._check_sym(Token.IDENT)
        closing_name = self.scanner.value
        closing_pos = self.scanner.position()
        self.scanner.get_next_symbol()  # consume closing module name

        self.sym_table.close_scope()  # leave global scope

        if closing_name != name:
            raise ParserError(
                f"Module name mismatch: expected '{name}', got '{closing_name}'",
                closing_pos,
            )

        self._expect(Token.PERIOD)  # consume '.'
        self._check_sym(Token.EOF)  # verify end of input

        return ast.Module(position=pos, ident=name, declarations=d)

    # ------------------------------------------------------------------
    # Built-in population helpers
    # ------------------------------------------------------------------

    def add_types(self) -> None:
        """Register the built-in types (INTEGER, BOOLEAN) in the current scope.

        Called by :meth:`module` immediately after opening the global scope.
        The type objects are defined in :mod:`oberon0_compiler.types`.
        """
        self.sym_table.add(types.integer)
        self.sym_table.add(types.boolean)

    def add_system_calls(self) -> None:
        """Register all built-in system calls in the current scope.

        Called by :meth:`module` after :meth:`add_types`.
        The system-call objects are defined in
        :mod:`oberon0_compiler.systemcalls`.
        """
        self.sym_table.add(systemcalls.OpenInput)
        self.sym_table.add(systemcalls.ReadInt)
        self.sym_table.add(systemcalls.eot)
        self.sym_table.add(systemcalls.WriteChar)
        self.sym_table.add(systemcalls.WriteInt)
        self.sym_table.add(systemcalls.WriteLn)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def parse(self) -> ast.Module:
        """Parse the complete source file and return the root AST node.

        This is the single public entry point.  It:

        1. Stores a reference to the scanner in the :mod:`~oberon0_compiler.ast`
           module (for downstream passes that need scanner positions).
        2. Calls ``scanner.get_next_symbol()`` to prime the lookahead.
        3. Delegates to :meth:`module` to parse the top-level production.

        Returns:
            The root :class:`~ast.Module` node of the parsed program.

        Raises:
            ParserError:  On any syntax or semantic error.
            ScannerError: On any lexical error (unterminated comment, etc.).
        """
        logger.debug("Starting parse")
        ast.actual_scanner = self.scanner
        self.scanner.get_next_symbol()  # prime the first lookahead
        return self.module()
