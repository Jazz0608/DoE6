#!/usr/bin/env python3
"""Extract KT002 Lua MISO-related .NET metadata and IL.

Run from the DOE6 repository root:
    .venv/bin/python analysis/kt002_phase2/extract_lua_miso_il.py

Input:
    analysis/kt002_phase2/ShizukuProtocol.dll

Outputs:
    analysis/kt002_phase2/lua_miso_symbols.txt
    analysis/kt002_phase2/lua_miso_methods.txt
    analysis/kt002_phase2/lua_miso_il.txt
"""

from __future__ import annotations

from pathlib import Path
import sys

import dnfile
from dncil.cil.body import CilMethodBody
from dncil.cil.body.reader import CilMethodBodyReaderBytes
from dncil.clr.token import StringToken, Token


ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_DIR = ROOT / "analysis" / "kt002_phase2"
DLL_PATH = ANALYSIS_DIR / "ShizukuProtocol.dll"

SYMBOLS_PATH = ANALYSIS_DIR / "lua_miso_symbols.txt"
METHODS_PATH = ANALYSIS_DIR / "lua_miso_methods.txt"
IL_PATH = ANALYSIS_DIR / "lua_miso_il.txt"

KEYWORDS = (
    "lua_miso",
    "luaputchar",
    "register_lua_fputc",
    "fputc",
    "datareceived",
    "callbackdeliverer",
    "generalreport",
    "generalrequest",
    "report",
)

TARGET_METHODS = {
    "LuaPutCharHandler_Setup",
    "Lua_MISO",
    "DataReceivedHandler",
    "DataReceived_Background_Handler",
    "CallbackDeliverer",
    "GeneralReport",
    "GeneralRequest",
    "MoveNext",
}

TABLES = {
    0x01: "TypeRef",
    0x02: "TypeDef",
    0x04: "Field",
    0x06: "MethodDef",
    0x0A: "MemberRef",
    0x11: "StandAloneSig",
    0x1B: "TypeSpec",
    0x2B: "MethodSpec",
    0x70: "UserString",
}


def row_name(row) -> str:
    for attribute in ("Name", "TypeName", "MethodName"):
        value = getattr(row, attribute, None)
        if value is not None:
            return str(value)
    return repr(row)


def resolve_token(pe, operand) -> str:
    value = operand.value
    table_number = value >> 24
    row_index = value & 0x00FFFFFF

    if table_number == 0x70:
        try:
            return "UserString:" + str(pe.net.user_strings.get(row_index))
        except Exception:
            return f"UserString:0x{value:08X}"

    table_name = TABLES.get(table_number)
    if table_name is None:
        return f"Token:0x{value:08X}"

    try:
        table = getattr(pe.net.mdtables, table_name)
        row = table.rows[row_index - 1]
        return f"{table_name}:{row_name(row)}"
    except Exception:
        return f"{table_name}:0x{value:08X}"


def format_operand(pe, operand) -> str:
    if operand is None:
        return ""
    if isinstance(operand, (Token, StringToken)):
        return resolve_token(pe, operand)
    if isinstance(operand, list):
        return "[" + ", ".join(format_operand(pe, item) for item in operand) + "]"
    return str(operand)


def is_relevant(type_name: str, method_name: str) -> bool:
    combined = f"{type_name}.{method_name}".lower()
    if any(keyword in combined for keyword in KEYWORDS):
        return True
    if method_name in TARGET_METHODS and (
        "lua" in type_name.lower()
        or "shizuku" in type_name.lower()
        or "datareceived" in type_name.lower()
    ):
        return True
    return False


def main() -> int:
    if not DLL_PATH.is_file():
        print(f"ERROR: DLL not found: {DLL_PATH}")
        return 2

    try:
        pe = dnfile.dnPE(str(DLL_PATH))
    except Exception as exc:
        print(f"ERROR: unable to parse .NET DLL: {exc}")
        return 3

    if not getattr(pe, "net", None):
        print("ERROR: input file does not contain .NET metadata")
        return 4

    symbol_lines: list[str] = []
    method_lines: list[str] = []
    il_lines: list[str] = []
    relevant_count = 0
    dumped_count = 0

    for type_def in pe.net.mdtables.TypeDef:
        type_name = str(type_def.TypeName)
        namespace = str(type_def.TypeNamespace or "")
        full_type = f"{namespace}.{type_name}" if namespace else type_name

        if any(keyword in full_type.lower() for keyword in KEYWORDS):
            symbol_lines.append(f"TYPE {full_type}")

        for method_index in type_def.MethodList:
            method = method_index.row
            method_name = str(method.Name)

            if not is_relevant(full_type, method_name):
                continue

            relevant_count += 1
            rva = int(method.Rva or 0)
            signature = bytes(method.Signature.value).hex() if method.Signature else ""

            symbol_lines.append(f"METHOD {full_type}.{method_name}")
            method_lines.append(
                f"{full_type}.{method_name}\tRVA=0x{rva:08X}\tSIG={signature}"
            )

            if rva == 0:
                continue

            il_lines.append("")
            il_lines.append(f"### {full_type}.{method_name} RVA=0x{rva:08X}")

            try:
                data = pe.get_data(rva, 65536)
                body = CilMethodBody(CilMethodBodyReaderBytes(data))
                for instruction in body.instructions:
                    operand_text = format_operand(pe, instruction.operand)
                    il_lines.append(
                        f"{instruction.offset:04X} "
                        f"{instruction.opcode.name:<16} {operand_text}"
                    )
                dumped_count += 1
            except Exception as exc:
                il_lines.append(f"ERROR decoding method body: {exc}")

    symbol_lines = sorted(set(symbol_lines), key=str.lower)
    method_lines = sorted(set(method_lines), key=str.lower)

    SYMBOLS_PATH.write_text("\n".join(symbol_lines) + "\n", encoding="utf-8")
    METHODS_PATH.write_text("\n".join(method_lines) + "\n", encoding="utf-8")
    IL_PATH.write_text("\n".join(il_lines).lstrip() + "\n", encoding="utf-8")

    print(f"DLL: {DLL_PATH}")
    print(f"Relevant methods: {relevant_count}")
    print(f"IL bodies decoded: {dumped_count}")
    print(f"Symbols: {SYMBOLS_PATH}")
    print(f"Methods: {METHODS_PATH}")
    print(f"IL: {IL_PATH}")

    if relevant_count == 0:
        print("WARNING: no relevant methods matched the current keyword list")
        return 1

    print("PASS: Lua MISO IL extraction completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
