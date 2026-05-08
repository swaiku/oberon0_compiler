(*
SPDX-FileCopyrightText: 2026 Jacques Supcik <jacques.supcik@hefr.ch>
SPDX-License-Identifier: MIT
*)

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
