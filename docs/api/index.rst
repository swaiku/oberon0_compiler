.. SPDX-FileCopyrightText: 2026 Jeremy Prin <prin.jeremy@protonmail.ch>
.. SPDX-License-Identifier: MIT

API Reference
=============

This section documents every public module of the Oberon-0 compiler.
The compiler is organised as a linear pipeline:

.. code-block:: text

   Source file
       |
       v
   [Scanner]  --tokens-->  [Parser]  --AST-->  (future passes)
       |                       |
   token.py              ast.py, sym_table.py,
   scanner.py            types.py, systemcalls.py

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: CLI
      :link: cli
      :link-type: doc

      Command-line entry point (``oberon0-compiler`` command).

   .. grid-item-card:: Scanner
      :link: scanner
      :link-type: doc

      Lexical analyser.  Reads source characters and emits
      :class:`~oberon0_compiler.token.Token` values.

   .. grid-item-card:: Token
      :link: token
      :link-type: doc

      Enumeration of every token recognised by the scanner.

   .. grid-item-card:: AST
      :link: ast
      :link-type: doc

      Abstract Syntax Tree node dataclasses produced by the parser.

   .. grid-item-card:: Symbol Table
      :link: sym_table
      :link-type: doc

      Scoped identifier bindings (variables, types, procedures).

   .. grid-item-card:: Types
      :link: types
      :link-type: doc

      Built-in primitive type descriptors (INTEGER, BOOLEAN).

   .. grid-item-card:: System Calls
      :link: systemcalls
      :link-type: doc

      Pre-declared I/O and runtime routine descriptors.

   .. grid-item-card:: Parser
      :link: parser
      :link-type: doc

      Recursive-descent parser that builds the AST.

.. toctree::
   :maxdepth: 2
   :hidden:
   :caption: Pipeline modules

   cli
   scanner
   token
   ast
   sym_table
   types
   systemcalls
   parser
