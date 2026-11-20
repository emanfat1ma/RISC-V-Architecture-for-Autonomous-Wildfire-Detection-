"""
isa.py - RV32I subset: encoding tables, decoder, disassembler and ALU helpers.

Supported instructions (32-bit base integer ISA, no M/A/F/C extensions):
  R : add sub sll slt sltu xor srl sra or and
  I : addi slti sltiu xori ori andi slli srli srai
  L/S: lw sw                       (word accesses only)
  B : beq bne blt bge bltu bgeu
  U : lui auipc          J: jal    JR: jalr       SYS: ecall (used as "halt")
"""

M32 = 0xFFFFFFFF


def s32(x):
    """Interpret x as a signed 32-bit integer."""
    x &= M32
    return x - (1 << 32) if x & 0x80000000 else x


def sext(v, bits):
    """Sign-extend the low `bits` bits of v."""
    v &= (1 << bits) - 1
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


# ---------------------------------------------------------------- registers
ABI = {"zero": 0, "ra": 1, "sp": 2, "gp": 3, "tp": 4, "fp": 8}
for _i, _n in enumerate(["t0", "t1", "t2"]):
    ABI[_n] = 5 + _i
ABI["s0"], ABI["s1"] = 8, 9
for _i in range(8):
    ABI[f"a{_i}"] = 10 + _i
for _i in range(2, 12):
    ABI[f"s{_i}"] = 16 + _i
for _i in range(3, 7):
    ABI[f"t{_i}"] = 25 + _i
for _i in range(32):
    ABI[f"x{_i}"] = _i

REG_NAMES = [f"x{i}" for i in range(32)]


# ---------------------------------------------------------------- opcode tables
OP_R, OP_I, OP_L, OP_S = 0x33, 0x13, 0x03, 0x23
OP_B, OP_JAL, OP_JALR, OP_LUI, OP_AUIPC, OP_SYS = 0x63, 0x6F, 0x67, 0x37, 0x17, 0x73

R_OPS = {"add": (0x00, 0), "sub": (0x20, 0), "sll": (0x00, 1), "slt": (0x00, 2),
         "sltu": (0x00, 3), "xor": (0x00, 4), "srl": (0x00, 5), "sra": (0x20, 5),
         "or": (0x00, 6), "and": (0x00, 7)}
I_OPS = {"addi": 0, "slti": 2, "sltiu": 3, "xori": 4, "ori": 6, "andi": 7}
SHIFT_I = {"slli": (0x00, 1), "srli": (0x00, 5), "srai": (0x20, 5)}
B_OPS = {"beq": 0, "bne": 1, "blt": 4, "bge": 5, "bltu": 6, "bgeu": 7}

R_REV = {v: k for k, v in R_OPS.items()}
I_REV = {v: k for k, v in I_OPS.items()}
B_REV = {v: k for k, v in B_OPS.items()}
I_BASE = {"addi": "add", "slti": "slt", "sltiu": "sltu", "xori": "xor", "ori": "or",
          "andi": "and", "slli": "sll", "srli": "srl", "srai": "sra"}

NOP = 0x00000013  # addi x0, x0, 0
ECALL = 0x00000073


class IllegalInstruction(Exception):
    pass


class Decoded:
    """Decoded instruction plus the control information the pipeline needs."""
    __slots__ = ("word", "fmt", "name", "rd", "rs1", "rs2", "imm", "uses_rs1",
                 "uses_rs2", "writes_rd", "is_load", "is_store", "is_branch",
                 "is_jal", "is_jalr")

    def __init__(self, word, fmt, name, rd=0, rs1=0, rs2=0, imm=0,
                 uses_rs1=False, uses_rs2=False, writes_rd=False):
        self.word, self.fmt, self.name = word, fmt, name
        self.rd, self.rs1, self.rs2, self.imm = rd, rs1, rs2, imm
        self.uses_rs1, self.uses_rs2, self.writes_rd = uses_rs1, uses_rs2, writes_rd
        self.is_load = name == "lw"
        self.is_store = name == "sw"
        self.is_branch = fmt == "B"
        self.is_jal = name == "jal"
        self.is_jalr = name == "jalr"


def decode(w):
    """Decode a 32-bit instruction word. Raises IllegalInstruction if unknown."""
    w &= M32
    op, rd, f3 = w & 0x7F, (w >> 7) & 31, (w >> 12) & 7
    rs1, rs2, f7 = (w >> 15) & 31, (w >> 20) & 31, (w >> 25) & 0x7F

    if op == OP_R:
        name = R_REV.get((f7, f3))
        if name is None:
            raise IllegalInstruction(f"bad R-type word {w:#010x}")
        return Decoded(w, "R", name, rd, rs1, rs2, 0, True, True, True)

    if op == OP_I:
        imm = sext(w >> 20, 12)
        if f3 == 1 and f7 == 0:
            return Decoded(w, "I", "slli", rd, rs1, 0, rs2, True, False, True)
        if f3 == 5 and f7 in (0x00, 0x20):
            return Decoded(w, "I", "srli" if f7 == 0 else "srai", rd, rs1, 0, rs2, True, False, True)
        if f3 in I_REV:
            return Decoded(w, "I", I_REV[f3], rd, rs1, 0, imm, True, False, True)
        raise IllegalInstruction(f"bad I-type word {w:#010x}")

    if op == OP_L and f3 == 2:
        return Decoded(w, "L", "lw", rd, rs1, 0, sext(w >> 20, 12), True, False, True)

    if op == OP_S and f3 == 2:
        imm = sext(((w >> 25) << 5) | ((w >> 7) & 0x1F), 12)
        return Decoded(w, "S", "sw", 0, rs1, rs2, imm, True, True, False)

    if op == OP_B and f3 in B_REV:
        imm = (((w >> 31) & 1) << 12) | (((w >> 7) & 1) << 11) | (((w >> 25) & 0x3F) << 5) | (((w >> 8) & 0xF) << 1)
        return Decoded(w, "B", B_REV[f3], 0, rs1, rs2, sext(imm, 13), True, True, False)

    if op == OP_JAL:
        imm = (((w >> 31) & 1) << 20) | (((w >> 12) & 0xFF) << 12) | (((w >> 20) & 1) << 11) | (((w >> 21) & 0x3FF) << 1)
        return Decoded(w, "J", "jal", rd, 0, 0, sext(imm, 21), False, False, True)

    if op == OP_JALR and f3 == 0:
        return Decoded(w, "JR", "jalr", rd, rs1, 0, sext(w >> 20, 12), True, False, True)

    if op == OP_LUI:
        return Decoded(w, "U", "lui", rd, 0, 0, w & 0xFFFFF000, False, False, True)

    if op == OP_AUIPC:
        return Decoded(w, "U", "auipc", rd, 0, 0, w & 0xFFFFF000, False, False, True)

    if w == ECALL:
        return Decoded(w, "SYS", "ecall")

    raise IllegalInstruction(f"illegal instruction word {w:#010x}")


# ---------------------------------------------------------------- execution helpers
def alu(name, a, b):
    """Base ALU operation (name is the register-register op name)."""
    a &= M32
    b &= M32
    if name == "add":
        r = a + b
    elif name == "sub":
        r = a - b
    elif name == "and":
        r = a & b
    elif name == "or":
        r = a | b
    elif name == "xor":
        r = a ^ b
    elif name == "sll":
        r = a << (b & 31)
    elif name == "srl":
        r = a >> (b & 31)
    elif name == "sra":
        r = s32(a) >> (b & 31)
    elif name == "slt":
        r = int(s32(a) < s32(b))
    elif name == "sltu":
        r = int(a < b)
    else:
        raise ValueError(f"unknown ALU op {name}")
    return r & M32


def branch_taken(name, a, b):
    a &= M32
    b &= M32
    if name == "beq":
        return a == b
    if name == "bne":
        return a != b
    if name == "blt":
        return s32(a) < s32(b)
    if name == "bge":
        return s32(a) >= s32(b)
    if name == "bltu":
        return a < b
    if name == "bgeu":
        return a >= b
    raise ValueError(name)


def exec_result(d, a, b, pc):
    """Value produced by the EX stage (ALU result / address / link value)."""
    f = d.fmt
    if f == "R":
        return alu(d.name, a, b)
    if f == "I":
        return alu(I_BASE[d.name], a, d.imm)
    if f in ("L", "S"):
        return (a + d.imm) & M32
    if d.name == "lui":
        return d.imm & M32
    if d.name == "auipc":
        return (pc + d.imm) & M32
    if f in ("J", "JR"):
        return (pc + 4) & M32
    raise ValueError(f"no EX result for {d.name}")


# ---------------------------------------------------------------- disassembler
def disasm(d):
    """Return assembly text for a Decoded instruction (or a raw word)."""
    if not isinstance(d, Decoded):
        d = decode(d)
    x = REG_NAMES
    f, n = d.fmt, d.name
    if f == "R":
        return f"{n} {x[d.rd]},{x[d.rs1]},{x[d.rs2]}"
    if f == "I":
        if n == "addi" and d.rd == 0 and d.rs1 == 0 and d.imm == 0:
            return "nop"
        return f"{n} {x[d.rd]},{x[d.rs1]},{d.imm}"
    if f == "L":
        return f"lw {x[d.rd]},{d.imm}({x[d.rs1]})"
    if f == "S":
        return f"sw {x[d.rs2]},{d.imm}({x[d.rs1]})"
    if f == "B":
        return f"{n} {x[d.rs1]},{x[d.rs2]},{d.imm:+d}"
    if f == "J":
        return f"jal {x[d.rd]},{d.imm:+d}"
    if f == "JR":
        return f"jalr {x[d.rd]},{x[d.rs1]},{d.imm}"
    if f == "U":
        return f"{n} {x[d.rd]},{d.imm >> 12:#x}"
    return n
