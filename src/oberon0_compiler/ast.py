# SPDX-FileCopyrightText: 2026 Jeremy Prin <prin.jeremy@protonmail.ch>
#
# SPDX-License-Identifier: MIT

"""
Abstract Syntax Tree (AST) node definitions for Oberon-0.
=========================================================

Every node in the tree is a frozen-like Python dataclass that inherits from
:class:`Node`.  The ``position`` field records the source location where the
node was parsed, which is used later for error reporting.

Each concrete node class implements :meth:`__str__` so that the whole tree
can be pretty-printed as valid (or near-valid) Oberon-0 source text.  This is
useful for debugging the parser output.

Node hierarchy
--------------

::

    Node
    +-- Expression                   (abstract base for all value-producing nodes)
    |   +-- Factor                   (abstract base for atomic expressions)
    |   |   +-- Number               (integer literal, e.g. 42)
    |   |   +-- Ident                (variable reference, e.g. x)
    |   |   +-- ProcedureCallFactor  (function call used as a value, e.g. eot())
    |   |   +-- ParenExpression      (parenthesised expression, e.g. (a + b))
    |   +-- SimpleExpression         (optional sign + terms joined by +/-)
    +-- Term                         (factors joined by * / DIV / MOD)
    +-- Statement                    (abstract base for executable statements)
    |   +-- Assignment               (e.g. x := x + 1)
    |   +-- ProcedureCallStatement   (e.g. WriteLn)
    +-- StatementSequence            (list of statements separated by ;)
    +-- VariableDeclaration          (one identifier in a VAR block)
    +-- Declarations                 (VAR block + nested procedure declarations)
    +-- ProcedureDeclaration         (PROCEDURE heading + body)
    +-- Module                       (top-level MODULE ... END .)

Scanner / parser relationship
-----------------------------

The module-level variable :data:`actual_scanner` is set to the active
:class:`~oberon0_compiler.scanner.Scanner` by
:meth:`~oberon0_compiler.parser.Parser.parse` before any parsing begins.
AST nodes receive a :class:`~oberon0_compiler.scanner.Position` snapshot at
construction time so that positions remain accurate even after the scanner
has advanced further.
"""

from dataclasses import dataclass, field
from typing import override

from . import sym_table as SYM
from .scanner import Position, Scanner

# ---------------------------------------------------------------------------
# Module-level scanner reference (set by Parser.parse before parsing begins)
# ---------------------------------------------------------------------------

#: The :class:`~oberon0_compiler.scanner.Scanner` currently in use.
#: Set to ``None`` when no parse is in progress.
actual_scanner: Scanner | None = None


# ---------------------------------------------------------------------------
# Base node
# ---------------------------------------------------------------------------


@dataclass
class Node:
    """Base class for every AST node.

    Attributes:
        position: Source-code location where this node starts.  Used by
                  downstream passes to report errors with file/line/column.
    """

    position: Position

    @override
    def __str__(self) -> str:
        return ""


# ---------------------------------------------------------------------------
# Abstract intermediate bases
# ---------------------------------------------------------------------------


@dataclass
class Expression(Node):
    """Abstract base for all expression nodes.

    An *expression* is any syntactic construct that produces a value.
    Concrete sub-classes include :class:`SimpleExpression` (the outermost
    expression form) and the various :class:`Factor` sub-types.
    """


@dataclass
class Factor(Expression):
    """Abstract base for atomic expression nodes (factors).

    A *factor* is the most tightly-binding syntactic unit: a literal number,
    a variable reference, a parenthesised sub-expression, or a procedure call
    used as a value.

    Grammar rule::

        factor = ident [ActualParameters] | number | "(" expression ")" .
    """


@dataclass
class Statement(Node):
    """Abstract base for statement nodes.

    A *statement* is an executable action: an assignment or a procedure call.
    The empty statement (allowed by the Oberon-0 grammar between semicolons)
    is represented as Python ``None`` in :class:`StatementSequence`, never as
    a :class:`Statement` instance.

    Grammar rule::

        statement = [assignment | ProcedureCall] .
    """


# ---------------------------------------------------------------------------
# Factor nodes  (leaves of the expression sub-tree)
# ---------------------------------------------------------------------------


@dataclass
class Number(Factor):
    """An integer literal.

    Grammar rule::

        number = integer .
        integer = digit {digit} .

    Attributes:
        value: The numeric value after conversion from the source string.

    Example::

        42   ->  Number(value=42)
    """

    value: int

    @override
    def __str__(self) -> str:
        return str(self.value)


@dataclass
class Ident(Factor):
    """A reference to a variable identifier.

    Grammar rule::

        factor = ident [ActualParameters] | ...

    When the identifier resolves to a :class:`~oberon0_compiler.sym_table.Variable`
    in the symbol table and no actual parameters are present, the parser
    creates an :class:`Ident` node.

    Attributes:
        symbol: The symbol-table entry for the referenced variable.

    Example::

        x   ->  Ident(symbol=LocalVariable('x', ...))
    """

    symbol: SYM.Variable

    @override
    def __str__(self) -> str:
        return self.symbol.name


@dataclass
class ProcedureCallFactor(Factor):
    """A procedure or system-call invocation used as an expression value.

    This covers cases such as ``eot()`` where a callable with a return type
    appears inside an expression.  The parser creates this node when the
    identifier resolves to a :class:`~oberon0_compiler.sym_table.SystemCall`
    or :class:`~oberon0_compiler.sym_table.ProcedureDefinition` in a *factor*
    position.

    Grammar rule::

        factor = ident [ActualParameters] | ...
        ActualParameters = "(" [expression {"," expression}] ")" .

    Attributes:
        symbol: The callable symbol (SystemCall or ProcedureDefinition).
        args:   Ordered list of actual-parameter expressions (may be empty).

    Example::

        eot()         ->  ProcedureCallFactor(symbol=eot, args=[])
        eot           ->  ProcedureCallFactor(symbol=eot, args=[])
    """

    symbol: SYM.Symbol
    args: list[Expression] = field(default_factory=list)

    @override
    def __str__(self) -> str:
        if self.args:
            arg_str = ", ".join(str(a) for a in self.args)
            return f"{self.symbol.name}({arg_str})"
        return self.symbol.name


@dataclass
class ParenExpression(Factor):
    """A parenthesised sub-expression.

    Grammar rule::

        factor = ... | "(" expression ")" .

    Attributes:
        expression: The inner :class:`Expression` enclosed by the parentheses.
                    In the simplified TP05 grammar this will always be a
                    :class:`SimpleExpression`, but the field is typed as the
                    abstract base so that future grammar extensions do not
                    require changes here.

    Example::

        (a + b)  ->  ParenExpression(expression=SimpleExpression(...))
    """

    expression: Expression

    @override
    def __str__(self) -> str:
        return f"({self.expression})"


# ---------------------------------------------------------------------------
# Term  (factors joined by multiplicative operators)
# ---------------------------------------------------------------------------


@dataclass
class Term(Node):
    """A sequence of factors connected by multiplicative operators.

    Grammar rule::

        term = factor {("*" | "DIV" | "MOD") factor} .

    The leading factor is stored in :attr:`factor`, and any additional
    ``(operator, factor)`` pairs are collected in :attr:`mulop_factors`.

    Attributes:
        factor:        The first (and possibly only) factor.
        mulop_factors: Zero or more ``(op, factor)`` pairs where *op* is one
                       of ``"*"``, ``"DIV"``, or ``"MOD"``.

    Example::

        2 * x          ->  Term(factor=Number(2), mulop_factors=[("*", Ident(x))])
        a DIV b MOD c  ->  Term(factor=Ident(a),
                                mulop_factors=[("DIV", Ident(b)),
                                               ("MOD", Ident(c))])
    """

    factor: Factor
    mulop_factors: list[tuple[str, Factor]] = field(default_factory=list)

    @override
    def __str__(self) -> str:
        tail = "".join(f" {op} {f}" for op, f in self.mulop_factors)
        return f"{self.factor}{tail}"


# ---------------------------------------------------------------------------
# SimpleExpression  (terms joined by additive operators, with optional sign)
# ---------------------------------------------------------------------------


@dataclass
class SimpleExpression(Expression):
    """An additive expression with an optional leading sign.

    In the simplified Oberon-0 grammar used for this practical work,
    ``expression = SimpleExpression``, so :class:`SimpleExpression` is the
    sole concrete :class:`Expression` type returned by the parser's
    ``expression()`` method.

    Grammar rule::

        SimpleExpression = ["+"|"-"] term {("+"|"-") term} .
        expression       = SimpleExpression .

    Attributes:
        sign:       ``"+"`` or ``"-"`` if a unary sign precedes the first
                    term; ``None`` otherwise.
        term:       The first (and possibly only) :class:`Term`.
        addop_terms: Zero or more ``(op, term)`` pairs where *op* is either
                     ``"+"`` or ``"-"``.

    Example::

        x + y      ->  SimpleExpression(sign=None, term=Term(Ident(x)),
                                        addop_terms=[('+', Term(Ident(y)))])
        -2 * x     ->  SimpleExpression(sign='-', term=Term(Number(2),
                                                            [('*', Ident(x))]),
                                        addop_terms=[])
    """

    sign: str | None
    term: Term
    addop_terms: list[tuple[str, Term]] = field(default_factory=list)

    @override
    def __str__(self) -> str:
        # Build the leading term string, prepending the unary sign if present.
        if self.sign:
            result = f"{self.sign}{self.term}"
        else:
            result = str(self.term)
        # Append each additional term together with its additive operator.
        for op, t in self.addop_terms:
            result += f" {op} {t}"
        return result


# ---------------------------------------------------------------------------
# Statement nodes
# ---------------------------------------------------------------------------


@dataclass
class Assignment(Statement):
    """An assignment statement.

    Grammar rule::

        assignment = ident ":=" expression .

    Attributes:
        symbol:     The symbol-table entry for the left-hand side variable.
        expression: The right-hand side :class:`Expression`.

    Example::

        z := x + y  ->  Assignment(symbol=LocalVariable('z'),
                                    expression=SimpleExpression(...))
    """

    symbol: SYM.Symbol
    expression: Expression

    @override
    def __str__(self) -> str:
        return f"{self.symbol.name} := {self.expression}"


@dataclass
class ProcedureCallStatement(Statement):
    """A procedure call used as a standalone statement.

    Grammar rule::

        ProcedureCall = ident [ActualParameters] .
        ActualParameters = "(" [expression {"," expression}] ")" .

    Attributes:
        symbol: The callable symbol (SystemCall or ProcedureDefinition).
        args:   Ordered list of actual-parameter expressions (may be empty).

    Examples::

        WriteLn           ->  ProcedureCallStatement(symbol=WriteLn, args=[])
        WriteInt(42, 5)   ->  ProcedureCallStatement(symbol=WriteInt,
                                                     args=[Number(42), Number(5)])
    """

    symbol: SYM.Symbol
    args: list[Expression] = field(default_factory=list)

    @override
    def __str__(self) -> str:
        if self.args:
            arg_str = ", ".join(str(a) for a in self.args)
            return f"{self.symbol.name}({arg_str})"
        return self.symbol.name


@dataclass
class StatementSequence(Node):
    """An ordered list of statements separated by semicolons.

    Empty statements (those that arise from a trailing semicolon before END)
    are silently dropped by the parser and are therefore never present in
    :attr:`statements`.

    Grammar rule::

        StatementSequence = statement {";" statement} .

    Attributes:
        statements: Zero or more concrete :class:`Statement` instances.

    Example::

        ReadInt(x); z := x + 1; WriteLn
            ->  StatementSequence(statements=[ProcedureCallStatement(ReadInt, ...),
                                              Assignment(z, ...),
                                              ProcedureCallStatement(WriteLn, [])])
    """

    statements: list[Statement] = field(default_factory=list)

    @override
    def __str__(self) -> str:
        return ";\n".join(str(s) for s in self.statements)


# ---------------------------------------------------------------------------
# Declaration nodes
# ---------------------------------------------------------------------------


@dataclass
class VariableDeclaration(Node):
    """A single variable declaration produced by a VAR block entry.

    One :class:`VariableDeclaration` is created per identifier in the
    ``IdentList``.  For example, ``VAR x, y : INTEGER;`` produces two
    :class:`VariableDeclaration` nodes (one for ``x``, one for ``y``).

    Grammar excerpt::

        IdentList ":" type ";"

    Attributes:
        symbol: The symbol-table entry (either :class:`~sym_table.LocalVariable`
                or :class:`~sym_table.GlobalVariable`) that was registered for
                this identifier.

    Example::

        VAR x : INTEGER;  ->  VariableDeclaration(symbol=LocalVariable('x', INTEGER, 0))
    """

    symbol: SYM.LocalVariable | SYM.GlobalVariable

    @override
    def __str__(self) -> str:
        return f"VAR {self.symbol.name}: {self.symbol.type_.name};"


@dataclass
class Declarations(Node):
    """All declarations in one scope (VAR block + nested procedures).

    Grammar rule::

        declarations =
            ["VAR" {IdentList ":" type ";"}]
            {ProcedureDeclaration ";"} .

    Attributes:
        var_declarations:       All variable declarations in the VAR block,
                                in source order.
        procedure_declarations: All nested procedure declarations, in source
                                order.

    Example for a procedure with ``VAR x, y: INTEGER;`` and no sub-procedures::

        Declarations(
            var_declarations=[VariableDeclaration(x), VariableDeclaration(y)],
            procedure_declarations=[],
        )
    """

    var_declarations: list[VariableDeclaration] = field(default_factory=list)
    procedure_declarations: list["ProcedureDeclaration"] = field(default_factory=list)

    @override
    def __str__(self) -> str:
        var_str = "\n".join(str(d) for d in self.var_declarations)
        proc_str = "\n".join(str(d) for d in self.procedure_declarations)
        # Drop empty strings so that the join does not produce blank lines.
        parts = [p for p in [var_str, proc_str] if p]
        return "\n".join(parts)


@dataclass
class ProcedureDeclaration(Node):
    """A complete procedure declaration (heading + body).

    Grammar rules::

        ProcedureHeading    = "PROCEDURE" ident ["*"] .
        ProcedureBody       = declarations ["BEGIN" StatementSequence] "END" ident .
        ProcedureDeclaration = ProcedureHeading ";" ProcedureBody .

    Attributes:
        symbol:      The :class:`~sym_table.ProcedureDefinition` registered in
                     the enclosing scope.
        exported:    ``True`` when the procedure name is followed by ``*``,
                     marking it as visible outside the module.
        declarations: Local VAR declarations and nested procedures.
        body:        The executable part of the procedure body (between
                     ``BEGIN`` and ``END``).  Contains an empty
                     :class:`StatementSequence` when there is no ``BEGIN``.

    Example::

        PROCEDURE Print42*;
        BEGIN
            WriteInt(42, 5);
            WriteLn;
        END Print42;
    """

    symbol: SYM.ProcedureDefinition
    exported: bool
    declarations: Declarations
    body: StatementSequence

    @override
    def __str__(self) -> str:
        export_marker = "*" if self.exported else ""
        decl_str = str(self.declarations)
        body_str = str(self.body)

        result = f"PROCEDURE {self.symbol.name}{export_marker};"
        if decl_str:
            result += "\n" + decl_str
        if body_str:
            result += "\nBEGIN\n" + body_str
        return result + f"\nEND {self.symbol.name}"


# ---------------------------------------------------------------------------
# Top-level module node
# ---------------------------------------------------------------------------


@dataclass
class Module(Node):
    """The root node of the AST, representing the entire Oberon-0 source file.

    Grammar rule::

        module =
            "MODULE" ident ";"
            declarations
            "END" ident "." .

    Attributes:
        ident:        The module name (must match both after MODULE and after END).
        declarations: The module-level declarations (global VAR block and
                      top-level procedure declarations).

    Example::

        MODULE Test;
            PROCEDURE Print42*;
            BEGIN
                WriteInt(42, 5);
                WriteLn;
            END Print42;
        END Test.
    """

    ident: str
    declarations: Declarations

    @override
    def __str__(self) -> str:
        decl_str = str(self.declarations)
        result = f"MODULE {self.ident};"
        if decl_str:
            result += "\n" + decl_str
        return result + f"\nEND {self.ident}."
