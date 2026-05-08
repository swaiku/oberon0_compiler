# SPDX-FileCopyrightText: 2026 Jeremy Prin <prin.jeremy@protonmail.ch> and Jacques Supcik <jacques.supcik@hefr.ch>
#
# SPDX-License-Identifier: MIT

"""
WebAssembly code generator for Oberon-0.

Transforms a type-checked AST into a WebAssembly binary module.
"""

from dataclasses import dataclass, field
from typing import BinaryIO, final, override

import wasm_gen as W  # noqa
from loguru import logger
from rich.console import Console
from wasm_gen import instructions as I  # noqa
from wasm_gen.type import i32_t

from . import ast
from . import sym_table as SYM
from .scanner import Position

console = Console()

system_calls = [
    (
        "OpenInput",
        W.BaseFunction(type=W.FunctionType(params=[], results=[])),
    ),
    (
        "ReadInt",
        W.BaseFunction(type=W.FunctionType(params=[i32_t], results=[])),
    ),
    (
        "eot",
        W.BaseFunction(type=W.FunctionType(params=[], results=[i32_t])),
    ),
    (
        "WriteChar",
        W.BaseFunction(type=W.FunctionType(params=[i32_t], results=[])),
    ),
    (
        "WriteInt",
        W.BaseFunction(type=W.FunctionType(params=[i32_t, i32_t], results=[])),
    ),
    (
        "WriteLn",
        W.BaseFunction(type=W.FunctionType(params=[], results=[])),
    ),
]


@final
class CodeGenError(Exception):
    def __init__(self, message: str, position: Position) -> None:
        super().__init__(message)
        self.position = position

    @override
    def __str__(self) -> str:
        p = self.position
        return (
            f"{self.args[0]} (File {p.file_name}, Line {p.line_no}, Column {p.col_no})"
        )


@dataclass
class CodeGenerator:
    code: W.Module | None = None
    _sp: W.BaseGlobal | None = None
    _current_function: list[W.Function] = field(default_factory=list)
    _proc_funcs: dict[str, W.Function] = field(default_factory=dict)

    def ensure(self, node: ast.Node, condition: bool, message: str) -> None:
        if not condition:
            raise CodeGenError(message, node.position)

    def current_function(self) -> W.Function:
        assert len(self._current_function) > 0
        return self._current_function[-1]

    def add_syscalls(self) -> None:
        logger.debug("Adding system calls")
        assert self.code is not None
        for name, func in system_calls:
            self.code.imports.append(
                W.Import(
                    node=func,
                    module="sys",
                    name=name,
                )
            )

    def add_memory(self) -> None:
        assert self.code is not None
        m1 = W.BaseMemory(type=W.MemoryType(min_pages=1))
        self.code.imports.append(W.Import(node=m1, module="env", name="memory"))

    def add_stack_pointer(self) -> None:
        assert self.code is not None
        self._sp = W.BaseGlobal(type=W.GlobalType(type=i32_t, mutable=True))
        self.code.imports.append(
            W.Import(node=self._sp, module="env", name="__stack_pointer")
        )

    def _stack_size_for(self, decls: ast.Declarations) -> int:
        size = 0
        for d in decls.var_declarations:
            size = max(size, d.symbol.offset + d.symbol.type_.size)
        return size

    def addr_of_symbol(self, node: ast.Node, sym: SYM.Symbol) -> None:
        assert self._sp is not None
        fn = self.current_function()
        if isinstance(sym, SYM.LocalVariable):
            fn.body.extend(
                [
                    I.GlobalGet(global_=self._sp),
                    I.I32Const(value=sym.offset),
                    I.I32Add(),
                ]
            )
        elif isinstance(sym, SYM.GlobalVariable):
            fn.body.extend(
                [
                    I.I32Const(value=sym.offset),
                ]
            )
        elif isinstance(sym, SYM.FormalParameter):
            self.ensure(node, sym.by_ref, "Symbol must be by reference")
            fn.body.extend(
                [
                    I.LocalGet(localidx=sym.index),
                ]
            )
        else:
            raise CodeGenError(
                f"Unknown instance of symbol: {sym} (NOT YET IMPLEMENTED)",
                node.position,
            )

    def addr_of_expr(self, expr: ast.Expression) -> None:
        self.ensure(expr, isinstance(expr, ast.SimpleExpression), "Expression expected")
        assert isinstance(expr, ast.SimpleExpression)
        self.ensure(expr, expr.sign is None, "Sign not allowed")
        self.ensure(
            expr,
            isinstance(expr.term.factor, ast.Ident),
            "Simple factor expected",
        )
        assert isinstance(expr.term.factor, ast.Ident)
        self.ensure(expr, len(expr.term.mulop_factors) == 0, "No mulop factors allowed")
        self.ensure(expr, len(expr.addop_terms) == 0, "No addop terms allowed")

        self.addr_of_symbol(expr, expr.term.factor.symbol)

    def expression(self, expr: ast.Expression) -> None:
        self.ensure(
            expr, isinstance(expr, ast.SimpleExpression), "SimpleExpression expected"
        )
        assert isinstance(expr, ast.SimpleExpression)

        if expr.sign == "-":
            self.current_function().body.append(I.I32Const(value=0))
            self.term(expr.term)
            self.current_function().body.append(I.I32Sub())
        else:
            self.term(expr.term)

        for op, term in expr.addop_terms:
            self.term(term)
            if op == "+":
                self.current_function().body.append(I.I32Add())
            elif op == "-":
                self.current_function().body.append(I.I32Sub())
            else:
                raise CodeGenError(f"Unknown addop: {op}", expr.position)

    def term(self, t: ast.Term) -> None:
        self.factor(t.factor)
        for op, factor in t.mulop_factors:
            self.factor(factor)
            if op == "*":
                self.current_function().body.append(I.I32Mul())
            elif op == "DIV":
                self.current_function().body.append(I.I32DivS())
            elif op == "MOD":
                self.current_function().body.append(I.I32RemS())
            else:
                raise CodeGenError(f"Unknown mulop: {op}", t.position)

    def procedure_call_statement(self, p: ast.ProcedureCallStatement) -> None:
        s = p.symbol
        if isinstance(s, SYM.SystemCall):
            self.ensure(
                p,
                s.return_type is None,
                "System call with a return value cannot be used as a statement",
            )
            self.system_call(p, s)
            return
        if isinstance(s, SYM.ProcedureDefinition):
            fn = self._proc_funcs.get(s.name)
            self.ensure(p, fn is not None, f"Unknown procedure: {s.name}")
            assert fn is not None
            self.current_function().body.append(I.Call(function=fn))
            return
        raise CodeGenError(f"Unknown procedure symbol: {s}", p.position)

    def procedure_call_factor(self, f: ast.ProcedureCallFactor) -> None:
        s = f.symbol
        if isinstance(s, SYM.SystemCall):
            self.ensure(
                f,
                s.return_type is not None,
                "System call used as an expression must return a value",
            )
            self.system_call(f, s)
            return
        raise CodeGenError(
            "Only system calls that return a value can be used in expressions",
            f.position,
        )

    def factor(self, f: ast.Factor) -> None:
        assert self.code is not None and self._sp is not None
        if isinstance(f, ast.Number):
            logger.debug(f"Number: {f.value}")
            self.current_function().body.append(I.I32Const(value=f.value))
        elif isinstance(f, ast.Ident):
            sym = f.symbol
            if isinstance(sym, SYM.LocalVariable):
                self.current_function().body.extend(
                    [
                        I.GlobalGet(global_=self._sp),
                        I.I32Const(value=sym.offset),
                        I.I32Add(),
                        I.I32Load(),
                    ]
                )
            elif isinstance(sym, SYM.GlobalVariable):
                self.current_function().body.extend(
                    [
                        I.I32Const(value=sym.offset),
                        I.I32Load(),
                    ]
                )
            elif isinstance(sym, SYM.FormalParameter):
                if sym.by_ref:
                    self.current_function().body.extend(
                        [
                            I.LocalGet(localidx=sym.index),
                            I.I32Load(),
                        ]
                    )
                else:
                    self.current_function().body.extend(
                        [
                            I.LocalGet(localidx=sym.index),
                        ]
                    )
            else:
                raise CodeGenError(f"Unknown symbol: {sym}", f.position)

        elif isinstance(f, ast.ProcedureCallFactor):
            self.procedure_call_factor(f)
        elif isinstance(f, ast.ParenExpression):
            self.expression(f.expression)
        else:
            raise CodeGenError(f"Unknown factor: {f}", f.position)

    def assignment(self, a: ast.Assignment) -> None:
        fn = self.current_function()
        sym = a.symbol
        self.ensure(a, sym is not None, f"Unknown symbol: {sym}")  # pyright: ignore[reportUnnecessaryComparison]
        assert sym is not None
        self.addr_of_symbol(a, sym)
        self.expression(a.expression)

        if isinstance(sym, SYM.FormalParameter) and not sym.by_ref:
            fn.body.append(I.LocalSet(localidx=sym.index))
        else:
            fn.body.append(I.I32Store())

    def statement(self, s: ast.Statement) -> None:
        if isinstance(s, ast.Assignment):
            self.assignment(s)
        elif isinstance(s, ast.ProcedureCallStatement):
            self.procedure_call_statement(s)
        else:
            raise CodeGenError(f"Unknown statement: {s}", s.position)

    def statement_sequence(self, seq: ast.StatementSequence) -> None:
        for s in seq.statements:
            self.statement(s)

    def system_call(
        self,
        p: ast.ProcedureCallStatement | ast.ProcedureCallFactor,
        s: SYM.SystemCall,
    ) -> None:
        logger.debug(f"System call: {p.symbol.name}")
        self.ensure(p, len(p.args) == len(s.params), "Wrong number of arguments")
        for i, a in enumerate(p.args):
            # TODO: check type
            if s.params[i].by_ref:
                logger.debug(f"argument: {a} by ref")
                self.addr_of_expr(a)
            else:
                logger.debug(f"argument: {a} by val")
                self.expression(a)

        self.current_function().body.append(I.Call(function=system_calls[s.index][1]))

    def procedure(self, p: ast.ProcedureDeclaration) -> None:
        assert self.code is not None and self._sp is not None

        f = self._proc_funcs.get(p.symbol.name)
        if f is None:
            f = W.Function(type=W.FunctionType(params=[], results=[]))
            self._proc_funcs[p.symbol.name] = f

        self._current_function.append(f)

        stack_size = self._stack_size_for(p.declarations)
        p.symbol.stack_size = stack_size

        # Procedure preamble (make room for local variables)
        if stack_size > 0:
            f.body.extend(
                [
                    I.GlobalGet(global_=self._sp),
                    I.I32Const(value=stack_size),
                    I.I32Sub(),
                    I.GlobalSet(global_=self._sp),
                ]
            )

        for nested in p.declarations.procedure_declarations:
            self.procedure(nested)

        self.statement_sequence(p.body)

        # Procedure postamble (reclaim memory for local variables)
        if stack_size > 0:
            f.body.extend(
                [
                    I.GlobalGet(global_=self._sp),
                    I.I32Const(value=stack_size),
                    I.I32Add(),
                    I.GlobalSet(global_=self._sp),
                ]
            )

        f.body.append(I.End())
        self.code.funcs.append(f)
        if p.exported:
            self.code.exports.append(W.Export(node=f, name=p.symbol.name))

        _ = self._current_function.pop()

    def generate(self, ast_: ast.Module, io: BinaryIO) -> None:
        self.ensure(ast_, isinstance(ast_, ast.Module), "Module expected")  # pyright: ignore[reportUnnecessaryIsInstance]
        self.code = W.Module()

        self.add_syscalls()
        self.add_memory()
        self.add_stack_pointer()

        d = ast_.declarations

        for p in d.procedure_declarations:
            self.procedure(p)

        _ = io.write(bytes(self.code))
