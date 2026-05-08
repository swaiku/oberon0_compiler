(*
SPDX-FileCopyrightText: 2026 Jacques Supcik <jacques.supcik@hefr.ch>
SPDX-License-Identifier: MIT
*)

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
