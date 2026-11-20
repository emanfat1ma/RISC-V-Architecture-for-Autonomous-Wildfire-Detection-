"""
assembler.py - A small two-pass RV32I assembler (so no external toolchain is needed).

Supports: all instructions in isa.py, labels, comments (#), and the directives
  .text  .data  .word v,...  .equ NAME,value  .globl (ignored)
Pseudo-instructions: nop li la mv not neg j jr ret beqz bnez bltz bgez bgt ble
Registers: x0..x31 and ABI names (zero, ra, sp, t0-t6, s0-s11, a0-a7).
"""
import re

from .isa import (ABI, B_OPS, I_OPS, M32, OP_AUIPC, OP_B, OP_I, OP_JAL, OP_JALR, OP_L,
                  OP_LUI, OP_R, OP_S, R_OPS, SHIFT_I, ECALL, s32, disasm)
from .memory import DMEM_BASE


class AsmError(Exception):
    pass


class Program:
    def __init__(self):
        self.words = []      # text section, one 32-bit word per instruction
        self.data = []       # data section words (loaded at DMEM_BASE)
        self.labels = {}     # name -> address
        self.listing = []    # (addr, word, source text)

    def dump(self):
        lines = []
        for addr, word, src in self.listing:
            lines.append(f"{addr:08x}:  {word:08x}   {disasm(word):<28} | {src}")
        return "\n".join(lines)


# ------------------------------------------------------------------ encoders
def enc_r(f7, rs2, rs1, f3, rd, op):
    return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op


def enc_i(imm, rs1, f3, rd, op):
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op


def enc_s(imm, rs2, rs1, f3, op):
    return (((imm >> 5) & 0x7F) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | ((imm & 0x1F) << 7) | op


def enc_b(imm, rs2, rs1, f3):
    imm &= 0x1FFF
    return ((((imm >> 12) & 1) << 31) | (((imm >> 5) & 0x3F) << 25) | (rs2 << 20) | (rs1 << 15)
            | (f3 << 12) | (((imm >> 1) & 0xF) << 8) | (((imm >> 11) & 1) << 7) | OP_B)


def enc_u(imm20, rd, op):
    return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | op


def enc_j(imm, rd):
    imm &= 0x1FFFFF
    return ((((imm >> 20) & 1) << 31) | (((imm >> 1) & 0x3FF) << 21) | (((imm >> 11) & 1) << 20)
            | (((imm >> 12) & 0xFF) << 12) | (rd << 7) | OP_JAL)


def li_seq(rd, val):
    """Expansion of `li rd, val` as a list of (mnemonic, ...) tuples."""
    val = s32(val)
    if -2048 <= val <= 2047:
        return [("addi", rd, 0, val)]
    hi = ((val + 0x800) >> 12) & 0xFFFFF
    lo = s32((val - (hi << 12)) & M32)
    seq = [("lui", rd, hi)]
    if lo != 0:
        seq.append(("addi", rd, rd, lo))
    return seq


# ------------------------------------------------------------------ assembler
class _Item:
    def __init__(self, mn, ops, ln, text, pc):
        self.mn, self.ops, self.ln, self.text, self.pc = mn, ops, ln, text, pc


def _const(tok, syms, ln):
    tok = tok.strip()
    try:
        return int(tok, 0)
    except ValueError:
        pass
    if tok in syms:
        return syms[tok]
    raise AsmError(f"line {ln}: cannot evaluate '{tok}'")


def _reg(tok, ln):
    t = tok.strip().lower()
    if t not in ABI:
        raise AsmError(f"line {ln}: unknown register '{tok}'")
    return ABI[t]


def _memop(tok, syms, ln):
    m = re.match(r"^(.*)\(\s*([\w]+)\s*\)$", tok.strip())
    if not m:
        raise AsmError(f"line {ln}: expected imm(reg), got '{tok}'")
    off = _const(m.group(1), syms, ln) if m.group(1).strip() else 0
    return off, _reg(m.group(2), ln)


def _check(val, lo, hi, what, ln):
    if not lo <= val <= hi:
        raise AsmError(f"line {ln}: {what} {val} out of range [{lo},{hi}]")
    return val


def assemble(source, defines=None):
    equ = dict(defines or {})
    labels = {}
    items = []
    data_words = []
    section, pc = "text", 0

    # ---------------- pass 1: layout
    for ln, raw in enumerate(source.splitlines(), 1):
        line = raw.split("#")[0].strip()
        while True:
            m = re.match(r"^([A-Za-z_.][\w.]*)\s*:\s*(.*)$", line)
            if not m:
                break
            name = m.group(1)
            if name in labels:
                raise AsmError(f"line {ln}: duplicate label '{name}'")
            labels[name] = pc if section == "text" else DMEM_BASE + 4 * len(data_words)
            line = m.group(2)
        if not line:
            continue
        parts = line.split(None, 1)
        mn = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        ops = [o.strip() for o in rest.split(",")] if rest.strip() else []

        if mn.startswith("."):
            if mn == ".text":
                section = "text"
            elif mn == ".data":
                section = "data"
            elif mn in (".globl", ".global"):
                pass
            elif mn in (".equ", ".set"):
                if len(ops) != 2:
                    raise AsmError(f"line {ln}: .equ NAME, value")
                if ops[0] not in equ:     # command-line defines win over file defaults
                    equ[ops[0]] = _const(ops[1], equ, ln)
            elif mn == ".word":
                if section != "data":
                    raise AsmError(f"line {ln}: .word only allowed in .data")
                for o in ops:
                    data_words.append(_const(o, {**equ, **labels}, ln) & M32)
            else:
                raise AsmError(f"line {ln}: unknown directive {mn}")
            continue

        if section != "text":
            raise AsmError(f"line {ln}: instruction in .data section")
        if mn == "li":
            if len(ops) != 2:
                raise AsmError(f"line {ln}: li rd, imm")
            size = len(li_seq(0, _const(ops[1], equ, ln)))
        elif mn == "la":
            size = 2
        else:
            size = 1
        items.append(_Item(mn, ops, ln, line, pc))
        pc += 4 * size

    # ---------------- pass 2: encode
    prog = Program()
    prog.data = data_words
    prog.labels = dict(labels)
    syms = {**equ, **labels}

    def target(tok, item):
        tok = tok.strip()
        if tok in labels:
            if labels[tok] >= DMEM_BASE:
                raise AsmError(f"line {item.ln}: cannot branch to data label '{tok}'")
            return labels[tok] - item.pc
        return _const(tok, equ, item.ln)

    def emit(item, word):
        prog.listing.append((4 * len(prog.words), word & M32, item.text))
        prog.words.append(word & M32)

    def encode_tuple(t, item):
        mn = t[0]
        ln = item.ln
        if mn == "addi":
            _check(t[3], -2048, 2047, "immediate", ln)
            return enc_i(t[3], t[2], 0, t[1], OP_I)
        if mn == "lui":
            return enc_u(t[2], t[1], OP_LUI)
        raise AssertionError(mn)

    for it in items:
        mn, o, ln = it.mn, it.ops, it.ln

        def need(n):
            if len(o) != n:
                raise AsmError(f"line {ln}: '{mn}' expects {n} operands, got {len(o)}")

        # ---- pseudo-instructions
        if mn == "nop":
            emit(it, enc_i(0, 0, 0, 0, OP_I)); continue
        if mn == "li":
            need(2)
            for t in li_seq(_reg(o[0], ln), _const(o[1], equ, ln)):
                emit(it, encode_tuple(t, it))
            continue
        if mn == "la":
            need(2)
            if o[1].strip() not in labels:
                raise AsmError(f"line {ln}: unknown label '{o[1]}'")
            val = labels[o[1].strip()]
            rd = _reg(o[0], ln)
            hi = ((val + 0x800) >> 12) & 0xFFFFF
            lo = s32((val - (hi << 12)) & M32)
            emit(it, enc_u(hi, rd, OP_LUI))
            emit(it, enc_i(lo, rd, 0, rd, OP_I))
            continue
        if mn == "mv":
            need(2); emit(it, enc_i(0, _reg(o[1], ln), 0, _reg(o[0], ln), OP_I)); continue
        if mn == "not":
            need(2); emit(it, enc_i(-1, _reg(o[1], ln), 4, _reg(o[0], ln), OP_I)); continue
        if mn == "neg":
            need(2); emit(it, enc_r(0x20, _reg(o[1], ln), 0, 0, _reg(o[0], ln), OP_R)); continue
        if mn == "j":
            need(1); emit(it, enc_j(_check(target(o[0], it), -(1 << 20), (1 << 20) - 2, "jump offset", ln), 0)); continue
        if mn == "jr":
            need(1); emit(it, enc_i(0, _reg(o[0], ln), 0, 0, OP_JALR)); continue
        if mn == "ret":
            need(0); emit(it, enc_i(0, 1, 0, 0, OP_JALR)); continue
        if mn in ("beqz", "bnez", "bltz", "bgez"):
            need(2)
            base = {"beqz": "beq", "bnez": "bne", "bltz": "blt", "bgez": "bge"}[mn]
            off = _check(target(o[1], it), -4096, 4094, "branch offset", ln)
            emit(it, enc_b(off, 0, _reg(o[0], ln), B_OPS[base])); continue
        if mn in ("bgt", "ble"):
            need(3)
            base = "blt" if mn == "bgt" else "bge"
            off = _check(target(o[2], it), -4096, 4094, "branch offset", ln)
            emit(it, enc_b(off, _reg(o[0], ln), _reg(o[1], ln), B_OPS[base])); continue

        # ---- real instructions
        if mn in R_OPS:
            need(3); f7, f3 = R_OPS[mn]
            emit(it, enc_r(f7, _reg(o[2], ln), _reg(o[1], ln), f3, _reg(o[0], ln), OP_R))
        elif mn in I_OPS:
            need(3)
            imm = _check(_const(o[2], equ, ln), -2048, 2047, "immediate", ln)
            emit(it, enc_i(imm, _reg(o[1], ln), I_OPS[mn], _reg(o[0], ln), OP_I))
        elif mn in SHIFT_I:
            need(3); f7, f3 = SHIFT_I[mn]
            sh = _check(_const(o[2], equ, ln), 0, 31, "shift amount", ln)
            emit(it, enc_i((f7 << 5) | sh, _reg(o[1], ln), f3, _reg(o[0], ln), OP_I))
        elif mn == "lw":
            need(2); off, base = _memop(o[1], syms, ln)
            _check(off, -2048, 2047, "offset", ln)
            emit(it, enc_i(off, base, 2, _reg(o[0], ln), OP_L))
        elif mn == "sw":
            need(2); off, base = _memop(o[1], syms, ln)
            _check(off, -2048, 2047, "offset", ln)
            emit(it, enc_s(off, _reg(o[0], ln), base, 2, OP_S))
        elif mn in B_OPS:
            need(3)
            off = _check(target(o[2], it), -4096, 4094, "branch offset", ln)
            emit(it, enc_b(off, _reg(o[1], ln), _reg(o[0], ln), B_OPS[mn]))
        elif mn == "jal":
            if len(o) == 1:
                rd, tgt = 1, o[0]
            else:
                need(2); rd, tgt = _reg(o[0], ln), o[1]
            emit(it, enc_j(_check(target(tgt, it), -(1 << 20), (1 << 20) - 2, "jump offset", ln), rd))
        elif mn == "jalr":
            if len(o) == 1:
                rd, rs1, imm = 1, _reg(o[0], ln), 0
            elif len(o) == 2 and "(" in o[1]:
                rd = _reg(o[0], ln); imm, rs1 = _memop(o[1], syms, ln)
            else:
                need(3); rd, rs1, imm = _reg(o[0], ln), _reg(o[1], ln), _const(o[2], equ, ln)
            emit(it, enc_i(_check(imm, -2048, 2047, "offset", ln), rs1, 0, rd, OP_JALR))
        elif mn in ("lui", "auipc"):
            need(2)
            emit(it, enc_u(_const(o[1], equ, ln), _reg(o[0], ln), OP_LUI if mn == "lui" else OP_AUIPC))
        elif mn == "ecall":
            emit(it, ECALL)
        else:
            raise AsmError(f"line {ln}: unknown instruction '{mn}'")

    return prog


def assemble_files(paths, defines=None):
    """Concatenate several .s files (shared labels / .equ) and assemble them as one image."""
    src = []
    for p in paths:
        with open(p) as f:
            src.append(f.read())
    return assemble("\n".join(src), defines)
