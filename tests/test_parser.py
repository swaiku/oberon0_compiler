# SPDX-FileCopyrightText: 2026 Jeremy Prin <prin.jeremy@protonmail.ch>
#
# SPDX-License-Identifier: MIT

"""
Unit tests for the Oberon-0 recursive-descent parser.

Each test feeds a small Oberon-0 source string through both the
:class:`~oberon0_compiler.scanner.Scanner` and the
:class:`~oberon0_compiler.parser.Parser`, then inspects the resulting AST.

Scanner role
------------
The scanner tokenises the raw source text into a stream of
:class:`~oberon0_compiler.token.Token` values.  The parser drives the
scanner by calling :meth:`~oberon0_compiler.scanner.Scanner.get_next_symbol`
and checks :attr:`~oberon0_compiler.scanner.Scanner.sym` for the current
lookahead token.

Parser role
-----------
The parser implements the simplified Oberon-0 grammar (TP05 version) as a
hand-written recursive-descent recogniser.  It builds an AST whose node types
live in :mod:`oberon0_compiler.ast` and resolves all identifiers against a
:class:`~oberon0_compiler.sym_table.SymbolTable`.

Test organisation
-----------------
* Helpers   -- make_parser() and assert helpers.
* Positive tests -- verify that valid programs produce the expected AST.
* Negative tests -- verify that invalid programs raise :class:`ParserError`.
"""

import io
import typing

import pytest

import oberon0_compiler.ast as AST
import oberon0_compiler.sym_table as SYM
from oberon0_compiler.parser import Parser, ParserError
from oberon0_compiler.scanner import Scanner
from oberon0_compiler.systemcalls import (
    OpenInput,
    ReadInt,
    WriteInt,
    WriteLn,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_parser(src: str) -> Parser:
    """Create a :class:`Parser` pre-loaded with *src*.

    The scanner is opened on an in-memory :class:`io.StringIO` stream so that
    no files need to exist on disk.

    Args:
        src: Oberon-0 source text.

    Returns:
        A ready-to-use :class:`Parser` instance (not yet started).
    """
    scanner = Scanner()
    scanner.open(io.StringIO(src))
    return Parser(scanner=scanner)


def parse(src: str) -> AST.Module:
    """Parse *src* and return the root :class:`~ast.Module` node.

    Convenience wrapper around :func:`make_parser` + :meth:`Parser.parse`.

    Args:
        src: Oberon-0 source text.

    Returns:
        The root :class:`~ast.Module` AST node.

    Raises:
        ParserError: On any syntax or semantic error.
    """
    return make_parser(src).parse()


def get_proc(module: AST.Module, index: int = 0) -> AST.ProcedureDeclaration:
    """Return the *index*-th procedure declaration of *module*."""
    return module.declarations.procedure_declarations[index]


def get_stmt(proc: AST.ProcedureDeclaration, index: int) -> AST.Statement:
    """Return the *index*-th statement in *proc*'s body."""
    return proc.body.statements[index]


def as_simple_expression(expr: AST.Expression) -> AST.SimpleExpression:
    """Narrow an Expression to SimpleExpression for test assertions."""
    assert isinstance(expr, AST.SimpleExpression)
    return expr


# ---------------------------------------------------------------------------
# Tests: minimal / structural
# ---------------------------------------------------------------------------


def test_empty_module() -> None:
    """The simplest valid module has no declarations and no body."""
    module = parse("MODULE M; END M.")

    assert module.ident == "M"
    assert module.declarations.var_declarations == []
    assert module.declarations.procedure_declarations == []


def test_module_str_empty() -> None:
    """str(Module) reproduces a sensible Oberon-0 module skeleton."""
    module = parse("MODULE Foo; END Foo.")
    text = str(module)

    assert "MODULE Foo;" in text
    assert "END Foo." in text


def test_module_name_mismatch_raises() -> None:
    """A module whose closing name differs from its opening name is an error."""
    with pytest.raises(ParserError, match="mismatch"):
        _ = parse("MODULE A; END B.")


def test_missing_period_raises() -> None:
    """A module missing the terminating '.' raises ParserError."""
    with pytest.raises(ParserError):
        _ = parse("MODULE M; END M")


def test_missing_end_raises() -> None:
    """A module missing END raises ParserError."""
    with pytest.raises(ParserError):
        _ = parse("MODULE M; M.")


# ---------------------------------------------------------------------------
# Tests: variable declarations
# ---------------------------------------------------------------------------


def test_single_var_declaration() -> None:
    """One VAR declaration creates one VariableDeclaration node."""
    module = parse("MODULE M; VAR x : INTEGER; END M.")

    var_decls = module.declarations.var_declarations
    assert len(var_decls) == 1
    assert var_decls[0].symbol.name == "x"
    assert var_decls[0].symbol.type_.name == "INTEGER"
    assert isinstance(var_decls[0].symbol, SYM.GlobalVariable)


def test_multiple_vars_same_line() -> None:
    """Comma-separated IdentList expands into one VariableDeclaration per name."""
    module = parse("MODULE M; VAR x, y, z : INTEGER; END M.")

    var_decls = module.declarations.var_declarations
    assert len(var_decls) == 3
    names = [d.symbol.name for d in var_decls]
    assert names == ["x", "y", "z"]


def test_var_offsets_sequential() -> None:
    """Each variable gets a sequentially increasing byte offset."""
    module = parse("MODULE M; VAR a, b, c : INTEGER; END M.")

    offsets = [d.symbol.offset for d in module.declarations.var_declarations]
    # INTEGER is 4 bytes, so offsets should be 0, 4, 8.
    assert offsets == [0, 4, 8]


def test_var_multiple_groups() -> None:
    """Multiple IdentList groups inside a single VAR block are all collected.

    The grammar allows exactly one VAR keyword per scope, but multiple
    'IdentList : type ;' groups can follow it:

        declarations = ["VAR" {IdentList ":" type ";"}] {ProcedureDeclaration ";"} .
    """
    module = parse("MODULE M;  VAR x : INTEGER;  y : BOOLEAN;  END M.")
    var_decls = module.declarations.var_declarations
    assert len(var_decls) == 2
    assert var_decls[0].symbol.name == "x"
    assert var_decls[1].symbol.name == "y"
    assert var_decls[1].symbol.type_.name == "BOOLEAN"


def test_unknown_type_raises() -> None:
    """Declaring a variable with an unknown type raises ParserError."""
    with pytest.raises(ParserError, match="not a known type"):
        _ = parse("MODULE M; VAR x : REAL; END M.")


def test_duplicate_var_raises() -> None:
    """Declaring the same identifier twice in the same scope raises an error."""
    with pytest.raises((KeyError, ParserError)):
        _ = parse("MODULE M; VAR x : INTEGER; VAR x : BOOLEAN; END M.")


def test_var_declaration_str() -> None:
    """str(VariableDeclaration) produces a readable summary."""
    module = parse("MODULE M; VAR count : INTEGER; END M.")
    text = str(module.declarations.var_declarations[0])
    assert "count" in text
    assert "INTEGER" in text


# ---------------------------------------------------------------------------
# Tests: procedure declarations
# ---------------------------------------------------------------------------


def test_empty_procedure() -> None:
    """A procedure with no body or declarations is valid."""
    module = parse("MODULE M; PROCEDURE Foo; END Foo; END M.")

    procs = module.declarations.procedure_declarations
    assert len(procs) == 1
    proc = procs[0]
    assert proc.symbol.name == "Foo"
    assert proc.exported is False
    assert proc.declarations.var_declarations == []
    assert proc.body.statements == []


def test_exported_procedure() -> None:
    """A procedure marked with '*' has exported=True."""
    module = parse("MODULE M; PROCEDURE Bar*; END Bar; END M.")

    proc = get_proc(module)
    assert proc.symbol.name == "Bar"
    assert proc.exported is True


def test_procedure_name_mismatch_raises() -> None:
    """Mismatched closing name in a procedure raises ParserError."""
    with pytest.raises(ParserError, match="mismatch"):
        _ = parse("MODULE M; PROCEDURE Foo; END Bar; END M.")


def test_procedure_with_local_var() -> None:
    """A procedure with a VAR block creates LocalVariable symbols."""
    src = "MODULE M;  PROCEDURE P;    VAR n : INTEGER;  END P;END M."
    module = parse(src)
    proc = get_proc(module)

    var_decls = proc.declarations.var_declarations
    assert len(var_decls) == 1
    assert var_decls[0].symbol.name == "n"
    assert isinstance(var_decls[0].symbol, SYM.LocalVariable)


def test_local_var_offsets() -> None:
    """Local variables inside a procedure get sequential offsets from 0."""
    src = "MODULE M;  PROCEDURE P;    VAR a, b : INTEGER;  END P;END M."
    module = parse(src)
    var_decls = get_proc(module).declarations.var_declarations
    offsets = [d.symbol.offset for d in var_decls]
    assert offsets == [0, 4]


def test_procedure_str() -> None:
    """str(ProcedureDeclaration) reproduces PROCEDURE / END structure."""
    src = "MODULE M; PROCEDURE Q*; END Q; END M."
    module = parse(src)
    text = str(get_proc(module))
    assert "PROCEDURE Q*;" in text
    assert "END Q" in text


def test_multiple_procedures() -> None:
    """Multiple procedures at module level are all collected."""
    src = (
        "MODULE M;  PROCEDURE A; END A;  PROCEDURE B; END B;  PROCEDURE C; END C;END M."
    )
    module = parse(src)
    names = [p.symbol.name for p in module.declarations.procedure_declarations]
    assert names == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# Tests: expressions and factors
# ---------------------------------------------------------------------------


def test_number_factor() -> None:
    """An integer literal in an assignment creates a Number node."""
    src = "MODULE M;  PROCEDURE P;    VAR x : INTEGER;  BEGIN x := 42 END P;END M."
    module = parse(src)
    assignment = typing.cast(AST.Assignment, get_stmt(get_proc(module), 0))
    assert isinstance(assignment, AST.Assignment)

    expr = assignment.expression
    assert isinstance(expr, AST.SimpleExpression)
    assert expr.sign is None
    factor = expr.term.factor
    assert isinstance(factor, AST.Number)
    assert factor.value == 42


def test_ident_factor() -> None:
    """A variable reference in an expression creates an Ident node."""
    src = "MODULE M;  PROCEDURE P;    VAR x, y : INTEGER;  BEGIN x := y END P;END M."
    module = parse(src)
    assignment = typing.cast(AST.Assignment, get_stmt(get_proc(module), 0))

    expr = as_simple_expression(assignment.expression)
    factor = expr.term.factor
    assert isinstance(factor, AST.Ident)
    assert factor.symbol.name == "y"


def test_paren_expression() -> None:
    """A parenthesised sub-expression creates a ParenExpression factor."""
    src = "MODULE M;  PROCEDURE P;    VAR x : INTEGER;  BEGIN x := (1) END P;END M."
    module = parse(src)
    assignment = typing.cast(AST.Assignment, get_stmt(get_proc(module), 0))

    expr = as_simple_expression(assignment.expression)
    factor = expr.term.factor
    assert isinstance(factor, AST.ParenExpression)
    inner = factor.expression
    assert isinstance(inner, AST.SimpleExpression)
    inner_factor = inner.term.factor
    assert isinstance(inner_factor, AST.Number)
    assert inner_factor.value == 1


def test_unary_minus() -> None:
    """A leading '-' sign is stored in SimpleExpression.sign."""
    src = "MODULE M;  PROCEDURE P;    VAR x : INTEGER;  BEGIN x := -1 END P;END M."
    module = parse(src)
    assignment = typing.cast(AST.Assignment, get_stmt(get_proc(module), 0))
    expr = as_simple_expression(assignment.expression)
    assert expr.sign == "-"
    factor = expr.term.factor
    assert isinstance(factor, AST.Number)
    assert factor.value == 1


def test_unary_plus() -> None:
    """A leading '+' sign is also captured in SimpleExpression.sign."""
    src = "MODULE M;  PROCEDURE P;    VAR x : INTEGER;  BEGIN x := +5 END P;END M."
    module = parse(src)
    assignment = typing.cast(AST.Assignment, get_stmt(get_proc(module), 0))
    expr = as_simple_expression(assignment.expression)
    assert expr.sign == "+"
    factor = expr.term.factor
    assert isinstance(factor, AST.Number)
    assert factor.value == 5


def test_additive_expression() -> None:
    """x + y produces a SimpleExpression with one addop_term entry."""
    src = (
        "MODULE M;"
        "  PROCEDURE P;"
        "    VAR x, y, z : INTEGER;"
        "  BEGIN z := x + y END P;"
        "END M."
    )
    module = parse(src)
    assignment = typing.cast(AST.Assignment, get_stmt(get_proc(module), 0))
    expr = as_simple_expression(assignment.expression)

    assert expr.sign is None
    leading_factor = expr.term.factor
    assert isinstance(leading_factor, AST.Ident)
    assert leading_factor.symbol.name == "x"

    assert len(expr.addop_terms) == 1
    op, term2 = expr.addop_terms[0]
    assert op == "+"
    factor2 = term2.factor
    assert isinstance(factor2, AST.Ident)
    assert factor2.symbol.name == "y"


def test_subtraction_expression() -> None:
    """x - y produces a SimpleExpression with op='-'."""
    src = (
        "MODULE M;"
        "  PROCEDURE P;"
        "    VAR x, y, z : INTEGER;"
        "  BEGIN z := x - y END P;"
        "END M."
    )
    module = parse(src)
    assignment = typing.cast(AST.Assignment, get_stmt(get_proc(module), 0))
    expr = as_simple_expression(assignment.expression)

    op, _ = expr.addop_terms[0]
    assert op == "-"


def test_multiplicative_term() -> None:
    """2 * x produces a Term with one mulop_factor entry."""
    src = (
        "MODULE M;  PROCEDURE P;    VAR x, y : INTEGER;  BEGIN y := 2 * x END P;END M."
    )
    module = parse(src)
    assignment = typing.cast(AST.Assignment, get_stmt(get_proc(module), 0))
    expr = as_simple_expression(assignment.expression)
    term = expr.term

    leading = term.factor
    assert isinstance(leading, AST.Number)
    assert leading.value == 2

    assert len(term.mulop_factors) == 1
    op, f2 = term.mulop_factors[0]
    assert op == "*"
    assert isinstance(f2, AST.Ident)
    assert f2.symbol.name == "x"


def test_div_operator() -> None:
    """DIV operator is captured with the correct string representation."""
    src = (
        "MODULE M;"
        "  PROCEDURE P;"
        "    VAR x, y : INTEGER;"
        "  BEGIN y := x DIV 2 END P;"
        "END M."
    )
    module = parse(src)
    assignment = typing.cast(AST.Assignment, get_stmt(get_proc(module), 0))
    expr = as_simple_expression(assignment.expression)
    term = expr.term
    op, _ = term.mulop_factors[0]
    assert op == "DIV"


def test_mod_operator() -> None:
    """MOD operator is captured correctly."""
    src = (
        "MODULE M;"
        "  PROCEDURE P;"
        "    VAR x, y : INTEGER;"
        "  BEGIN y := x MOD 3 END P;"
        "END M."
    )
    module = parse(src)
    assignment = typing.cast(AST.Assignment, get_stmt(get_proc(module), 0))
    expr = as_simple_expression(assignment.expression)
    term = expr.term
    op, _ = term.mulop_factors[0]
    assert op == "MOD"


def test_complex_expression_str() -> None:
    """str() of a complex expression reproduces the operators and operands."""
    src = (
        "MODULE M;"
        "  PROCEDURE P;"
        "    VAR x, y, z : INTEGER;"
        "  BEGIN z := x + 2 * y END P;"
        "END M."
    )
    module = parse(src)
    assignment = typing.cast(AST.Assignment, get_stmt(get_proc(module), 0))
    text = str(assignment)
    assert "z :=" in text
    assert "x" in text
    assert "+" in text
    assert "2" in text
    assert "*" in text
    assert "y" in text


def test_undeclared_variable_in_expression_raises() -> None:
    """Referencing an undeclared identifier raises ParserError."""
    src = (
        "MODULE M;  PROCEDURE P;    VAR x : INTEGER;  BEGIN x := undefined END P;END M."
    )
    with pytest.raises(ParserError, match="[Uu]ndeclared"):
        _ = parse(src)


# ---------------------------------------------------------------------------
# Tests: assignment statements
# ---------------------------------------------------------------------------


def test_assignment_statement() -> None:
    """A simple assignment creates an Assignment node with the correct symbol."""
    src = (
        "MODULE M;"
        "  PROCEDURE P;"
        "    VAR result : INTEGER;"
        "  BEGIN result := 0 END P;"
        "END M."
    )
    module = parse(src)
    stmt = get_stmt(get_proc(module), 0)

    assert isinstance(stmt, AST.Assignment)
    assert stmt.symbol.name == "result"


def test_assignment_str() -> None:
    """str(Assignment) contains ':=' and both sides."""
    src = "MODULE M;  PROCEDURE P;    VAR n : INTEGER;  BEGIN n := 99 END P;END M."
    module = parse(src)
    stmt = get_stmt(get_proc(module), 0)
    text = str(stmt)
    assert ":=" in text
    assert "n" in text
    assert "99" in text


def test_assignment_to_undeclared_raises() -> None:
    """Assigning to an undeclared variable raises ParserError."""
    src = "MODULE M;  PROCEDURE P;  BEGIN ghost := 1 END P;END M."
    with pytest.raises(ParserError):
        _ = parse(src)


def test_assignment_lhs_must_be_variable() -> None:
    """Assigning to a non-variable (e.g. a procedure name) raises ParserError."""
    src = "MODULE M;  PROCEDURE P;  END P;  PROCEDURE Q;  BEGIN P := 1 END Q;END M."
    with pytest.raises(ParserError):
        _ = parse(src)


# ---------------------------------------------------------------------------
# Tests: procedure call statements
# ---------------------------------------------------------------------------


def test_procedure_call_no_args() -> None:
    """A call to a no-argument procedure creates the correct node."""
    src = "MODULE M;  PROCEDURE P*;  BEGIN WriteLn END P;END M."
    module = parse(src)
    stmt = get_stmt(get_proc(module), 0)

    assert isinstance(stmt, AST.ProcedureCallStatement)
    assert stmt.symbol is WriteLn
    assert stmt.args == []


def test_procedure_call_with_args() -> None:
    """WriteInt(42, 5) produces two argument expressions."""
    src = "MODULE M;  PROCEDURE P*;  BEGIN WriteInt(42, 5) END P;END M."
    module = parse(src)
    stmt = typing.cast(AST.ProcedureCallStatement, get_stmt(get_proc(module), 0))

    assert stmt.symbol is WriteInt
    assert len(stmt.args) == 2

    arg0 = typing.cast(AST.SimpleExpression, stmt.args[0])
    factor0 = arg0.term.factor
    assert isinstance(factor0, AST.Number)
    assert factor0.value == 42

    arg1 = typing.cast(AST.SimpleExpression, stmt.args[1])
    factor1 = arg1.term.factor
    assert isinstance(factor1, AST.Number)
    assert factor1.value == 5


def test_procedure_call_str() -> None:
    """str(ProcedureCallStatement) reproduces name and argument list."""
    src = "MODULE M;  PROCEDURE P*;  BEGIN WriteInt(1, 2) END P;END M."
    module = parse(src)
    text = str(get_stmt(get_proc(module), 0))
    assert "WriteInt" in text
    assert "1" in text
    assert "2" in text


def test_call_undeclared_procedure_raises() -> None:
    """Calling an undeclared procedure raises ParserError."""
    src = "MODULE M;  PROCEDURE P;  BEGIN Ghost END P;END M."
    with pytest.raises(ParserError):
        _ = parse(src)


def test_call_variable_as_procedure_raises() -> None:
    """Using a variable name as a procedure call raises ParserError."""
    src = "MODULE M;  PROCEDURE P;    VAR x : INTEGER;  BEGIN x END P;END M."
    with pytest.raises(ParserError):
        _ = parse(src)


# ---------------------------------------------------------------------------
# Tests: statement sequences
# ---------------------------------------------------------------------------


def test_empty_statement_sequence() -> None:
    """A procedure body with only a trailing ';' produces no statements."""
    src = "MODULE M;  PROCEDURE P;  BEGIN WriteLn; END P;END M."
    module = parse(src)
    stmts = get_proc(module).body.statements
    # Trailing semicolon creates an empty statement that is discarded.
    assert len(stmts) == 1


def test_multiple_statements() -> None:
    """Multiple semicolon-separated statements are all collected."""
    src = (
        "MODULE M;"
        "  PROCEDURE P*;"
        "    VAR x : INTEGER;"
        "  BEGIN"
        "    OpenInput;"
        "    ReadInt(x);"
        "    WriteLn"
        "  END P;"
        "END M."
    )
    module = parse(src)
    stmts = get_proc(module).body.statements
    assert len(stmts) == 3

    assert isinstance(stmts[0], AST.ProcedureCallStatement)
    assert stmts[0].symbol is OpenInput  # type: ignore[union-attr]

    assert isinstance(stmts[1], AST.ProcedureCallStatement)
    assert stmts[1].symbol is ReadInt  # type: ignore[union-attr]

    assert isinstance(stmts[2], AST.ProcedureCallStatement)
    assert stmts[2].symbol is WriteLn  # type: ignore[union-attr]


def test_statement_sequence_str() -> None:
    """str(StatementSequence) joins statements with ';\\n'."""
    src = "MODULE M;  PROCEDURE P*;  BEGIN WriteLn; WriteLn END P;END M."
    module = parse(src)
    body_str = str(get_proc(module).body)
    assert "WriteLn" in body_str
    assert ";" in body_str


# ---------------------------------------------------------------------------
# Tests: ReadInt with by-reference argument
# ---------------------------------------------------------------------------


def test_readint_variable_arg() -> None:
    """ReadInt(x) passes the variable 'x' as its argument."""
    src = "MODULE M;  PROCEDURE P*;    VAR x : INTEGER;  BEGIN ReadInt(x) END P;END M."
    module = parse(src)
    stmt = typing.cast(AST.ProcedureCallStatement, get_stmt(get_proc(module), 0))

    assert stmt.symbol is ReadInt
    assert len(stmt.args) == 1

    arg = typing.cast(AST.SimpleExpression, stmt.args[0])
    arg_factor = arg.term.factor
    assert isinstance(arg_factor, AST.Ident)
    assert arg_factor.symbol.name == "x"


# ---------------------------------------------------------------------------
# Tests: full example programs from the TP specification
# ---------------------------------------------------------------------------


# --- print42.mod ------------------------------------------------------------

_PRINT42 = """\
MODULE Test;

    PROCEDURE Print42*;
    BEGIN
        WriteInt(42, 5);
        WriteLn;
    END Print42;

END Test.
"""


def test_print42_module_name() -> None:
    """print42.mod: module is named 'Test'."""
    module = parse(_PRINT42)
    assert module.ident == "Test"


def test_print42_one_procedure() -> None:
    """print42.mod: exactly one procedure declared at module level."""
    module = parse(_PRINT42)
    assert len(module.declarations.procedure_declarations) == 1


def test_print42_procedure_name_and_export() -> None:
    """print42.mod: procedure is 'Print42' and is exported."""
    proc = get_proc(parse(_PRINT42))
    assert proc.symbol.name == "Print42"
    assert proc.exported is True


def test_print42_no_local_vars() -> None:
    """print42.mod: Print42 declares no local variables."""
    proc = get_proc(parse(_PRINT42))
    assert proc.declarations.var_declarations == []


def test_print42_two_statements() -> None:
    """print42.mod: Print42 body has WriteInt and WriteLn."""
    proc = get_proc(parse(_PRINT42))
    stmts = proc.body.statements
    assert len(stmts) == 2


def test_print42_writeint_args() -> None:
    """print42.mod: WriteInt is called with arguments 42 and 5."""
    proc = get_proc(parse(_PRINT42))
    stmt = typing.cast(AST.ProcedureCallStatement, proc.body.statements[0])

    assert stmt.symbol is WriteInt

    arg0 = typing.cast(AST.SimpleExpression, stmt.args[0])
    factor0 = arg0.term.factor
    assert isinstance(factor0, AST.Number)
    assert factor0.value == 42

    arg1 = typing.cast(AST.SimpleExpression, stmt.args[1])
    factor1 = arg1.term.factor
    assert isinstance(factor1, AST.Number)
    assert factor1.value == 5


def test_print42_writeln_no_args() -> None:
    """print42.mod: WriteLn is called with no arguments."""
    proc = get_proc(parse(_PRINT42))
    stmt = typing.cast(AST.ProcedureCallStatement, proc.body.statements[1])
    assert stmt.symbol is WriteLn
    assert stmt.args == []


def test_print42_str_roundtrip() -> None:
    """print42.mod: str(module) contains the key structural keywords."""
    text = str(parse(_PRINT42))
    assert "MODULE Test;" in text
    assert "PROCEDURE Print42*;" in text
    assert "BEGIN" in text
    assert "WriteInt" in text
    assert "WriteLn" in text
    assert "END Print42" in text
    assert "END Test." in text


# --- printx.mod -------------------------------------------------------------

_PRINTX = """\
MODULE Test;

    PROCEDURE Print2X*;
    VAR x, y : INTEGER;
    BEGIN
        OpenInput;
        ReadInt(x);
        WriteInt(2 * x, 5);
        WriteLn;
    END Print2X;

END Test.
"""


def test_printx_module_name() -> None:
    """printx.mod: module is named 'Test'."""
    assert parse(_PRINTX).ident == "Test"


def test_printx_procedure() -> None:
    """printx.mod: procedure is 'Print2X' and is exported."""
    proc = get_proc(parse(_PRINTX))
    assert proc.symbol.name == "Print2X"
    assert proc.exported is True


def test_printx_two_local_vars() -> None:
    """printx.mod: Print2X declares exactly two local variables (x and y)."""
    var_decls = get_proc(parse(_PRINTX)).declarations.var_declarations
    assert len(var_decls) == 2
    names = [d.symbol.name for d in var_decls]
    assert names == ["x", "y"]
    for d in var_decls:
        assert isinstance(d.symbol, SYM.LocalVariable)
        assert d.symbol.type_.name == "INTEGER"


def test_printx_four_statements() -> None:
    """printx.mod: Print2X body has four statements."""
    stmts = get_proc(parse(_PRINTX)).body.statements
    assert len(stmts) == 4


def test_printx_writeint_2x() -> None:
    """printx.mod: WriteInt receives '2 * x' as its first argument."""
    stmts = get_proc(parse(_PRINTX)).body.statements
    write_stmt = typing.cast(AST.ProcedureCallStatement, stmts[2])
    assert write_stmt.symbol is WriteInt

    # First argument: 2 * x
    arg0 = typing.cast(AST.SimpleExpression, write_stmt.args[0])
    term = arg0.term
    leading = term.factor
    assert isinstance(leading, AST.Number)
    assert leading.value == 2

    assert len(term.mulop_factors) == 1
    op, f2 = term.mulop_factors[0]
    assert op == "*"
    assert isinstance(f2, AST.Ident)
    assert f2.symbol.name == "x"


# --- add.mod ----------------------------------------------------------------

_ADD = """\
MODULE Test;

    PROCEDURE Add*;
        VAR x, y, z: INTEGER;
    BEGIN
        OpenInput;
        ReadInt(x);
        ReadInt(y);
        z := x + y;
        WriteInt(z, 5);
        WriteLn;
    END Add;

END Test.
"""


def test_add_module_name() -> None:
    """add.mod: module is named 'Test'."""
    assert parse(_ADD).ident == "Test"


def test_add_procedure() -> None:
    """add.mod: procedure is 'Add' and is exported."""
    proc = get_proc(parse(_ADD))
    assert proc.symbol.name == "Add"
    assert proc.exported is True


def test_add_three_local_vars() -> None:
    """add.mod: Add declares three local variables (x, y, z)."""
    var_decls = get_proc(parse(_ADD)).declarations.var_declarations
    assert len(var_decls) == 3
    names = [d.symbol.name for d in var_decls]
    assert names == ["x", "y", "z"]


def test_add_six_statements() -> None:
    """add.mod: Add body has exactly six statements."""
    stmts = get_proc(parse(_ADD)).body.statements
    assert len(stmts) == 6


def test_add_assignment_z_equals_x_plus_y() -> None:
    """add.mod: 'z := x + y' is the fourth statement and has correct structure."""
    stmts = get_proc(parse(_ADD)).body.statements
    assign = typing.cast(AST.Assignment, stmts[3])

    assert isinstance(assign, AST.Assignment)
    assert assign.symbol.name == "z"

    expr = as_simple_expression(assign.expression)
    assert expr.sign is None

    # Leading term is 'x'
    leading_factor = expr.term.factor
    assert isinstance(leading_factor, AST.Ident)
    assert leading_factor.symbol.name == "x"

    # One addop_term: '+ y'
    assert len(expr.addop_terms) == 1
    op, term2 = expr.addop_terms[0]
    assert op == "+"
    factor2 = term2.factor
    assert isinstance(factor2, AST.Ident)
    assert factor2.symbol.name == "y"


def test_add_writeint_z() -> None:
    """add.mod: WriteInt is called with variable z and width 5."""
    stmts = get_proc(parse(_ADD)).body.statements
    stmt = typing.cast(AST.ProcedureCallStatement, stmts[4])

    assert stmt.symbol is WriteInt

    arg0 = typing.cast(AST.SimpleExpression, stmt.args[0])
    factor0 = arg0.term.factor
    assert isinstance(factor0, AST.Ident)
    assert factor0.symbol.name == "z"

    arg1 = typing.cast(AST.SimpleExpression, stmt.args[1])
    factor1 = arg1.term.factor
    assert isinstance(factor1, AST.Number)
    assert factor1.value == 5


def test_add_str_roundtrip() -> None:
    """add.mod: str(module) contains all key identifiers and keywords."""
    text = str(parse(_ADD))
    for keyword in ("MODULE", "PROCEDURE", "BEGIN", "END", "VAR"):
        assert keyword in text
    for name in ("Test", "Add", "x", "y", "z"):
        assert name in text


# ---------------------------------------------------------------------------
# Tests: scope isolation
# ---------------------------------------------------------------------------


def test_local_var_not_visible_outside_procedure() -> None:
    """A variable declared inside one procedure is not visible in another."""
    src = (
        "MODULE M;"
        "  PROCEDURE A;"
        "    VAR secret : INTEGER;"
        "  END A;"
        "  PROCEDURE B;"
        "    VAR x : INTEGER;"
        "  BEGIN x := secret END B;"  # 'secret' is out of scope here
        "END M."
    )
    with pytest.raises(ParserError):
        _ = parse(src)


def test_global_var_visible_in_procedure() -> None:
    """A module-level variable is visible inside a procedure body."""
    src = "MODULE M;  VAR g : INTEGER;  PROCEDURE P;  BEGIN g := 1 END P;END M."
    module = parse(src)
    # If we get here without error the scope look-up worked correctly.
    proc = get_proc(module)
    assign = typing.cast(AST.Assignment, get_stmt(proc, 0))
    assert assign.symbol.name == "g"
    assert isinstance(assign.symbol, SYM.GlobalVariable)


def test_system_calls_in_scope() -> None:
    """All built-in system calls are visible inside any procedure."""
    src = (
        "MODULE M;"
        "  PROCEDURE P*;"
        "    VAR x : INTEGER;"
        "  BEGIN"
        "    OpenInput;"
        "    ReadInt(x);"
        "    WriteInt(x, 10);"
        "    WriteLn"
        "  END P;"
        "END M."
    )
    # Must parse without error.
    module = parse(src)
    assert len(get_proc(module).body.statements) == 4
