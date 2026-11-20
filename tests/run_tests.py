"""
run_tests.py - Verification (Step 3/4/11): every program must finish in the SAME
architectural state on the pipelined core as on the golden ISA model.

Checked per (program, pipeline configuration):
  registers, data RAM, MMIO write log, retired-instruction count
and, for ecall-terminated programs, the cycle identity
  cycles == retired + 4 (pipeline fill) + data_stalls + control_penalty
Also: known-answer checks on the golden model, assembler encoding checks, and the
firmware images (boot+handler, poll+handler) under several sensor inputs.

Run:  python main.py test      (or: python -m tests.run_tests)
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sim.assembler import assemble, assemble_files
from sim.golden import GoldenCPU
from sim.memory import Bus, DMEM_BASE
from sim.pipeline import PipelineCPU

ASM = os.path.join(ROOT, "asm")
CONFIGS = [(fw, pol) for fw in (True, False) for pol in PipelineCPU.POLICIES]
DEFINES = {"TEMP_THRESH": 60, "SMOKE_THRESH": 30, "REQUIRE_SMOKE": 1}

ENCODINGS = {
    "addi x1, x0, 5": 0x00500093, "add x3, x1, x2": 0x002081B3, "sub x3, x1, x2": 0x402081B3,
    "lw x5, 8(x2)": 0x00812283, "sw x5, 8(x2)": 0x00512423, "beq x1, x2, 8": 0x00208463,
    "jal x1, 8": 0x008000EF, "lui x1, 0x12345": 0x123450B7, "srai x1, x2, 3": 0x40315093,
}


def reg(cpu, name):
    from sim.isa import ABI
    return cpu.regs[ABI[name]]


def signed(v):
    return v - (1 << 32) if v & 0x80000000 else v


def dmem_words(bus, base, n):
    o = base - DMEM_BASE
    return [int.from_bytes(bus.dmem[o + 4 * i:o + 4 * i + 4], "little") for i in range(n)]


# known-answer checks on the golden model: name -> function(cpu, bus, program) -> bool
EXPECT = {
    "arith": lambda c, b, p: (reg(c, "t2"), reg(c, "t3"), reg(c, "t4"), reg(c, "t5"), reg(c, "t6"),
                              reg(c, "s0"), reg(c, "s1"), signed(reg(c, "s3")), reg(c, "s4"),
                              reg(c, "s5"), reg(c, "s6"), reg(c, "s7"), reg(c, "s8"), reg(c, "s9"),
                              reg(c, "s10"), reg(c, "s11"))
    == (22, 8, 7, 15, 8, 240, 60, -4, 15, 1, 0, 0x12345678, 0x80000000, 100000, 10, 6),
    "raw_chain": lambda c, b, p: (reg(c, "t1"), reg(c, "t6"), reg(c, "s1")) == (2, 21, 55),
    "loaduse": lambda c, b, p: reg(c, "t2") == 180 and reg(c, "t5") == 181,
    "fib": lambda c, b, p: reg(c, "t0") == 6765,
    "bubble_sort": lambda c, b, p: dmem_words(b, p.labels["vals"], 12) == sorted(range(12)),
    "branches": lambda c, b, p: reg(c, "t2") == 20,
    "call": lambda c, b, p: (reg(c, "s0"), reg(c, "s1")) == (15, 55),
    "memcpy": lambda c, b, p: dmem_words(b, p.labels["dst"], 16) == list(range(1, 17)) and reg(c, "s0") == 136,
}


def compare(golden, gbus, pipe, pbus):
    problems = []
    if golden.regs != pipe.regs:
        diff = [i for i in range(32) if golden.regs[i] != pipe.regs[i]]
        problems.append(f"regs differ x{diff}")
    if gbus.dmem != pbus.dmem:
        problems.append("data RAM differs")
    if gbus.mmio_log != pbus.mmio_log:
        problems.append("MMIO log differs")
    if golden.retired != pipe.retired:
        problems.append(f"retired {golden.retired} vs {pipe.retired}")
    return problems


def run_pair(prog, fw, pol, temp=0, smoke=0):
    gbus, pbus = Bus(prog, temp, smoke), Bus(prog, temp, smoke)
    g = GoldenCPU(gbus).run()
    p = PipelineCPU(pbus, forwarding=fw, branch_policy=pol).run()
    return g, gbus, p, pbus


def run_all(verbose=True):
    results = []     # dicts: name, config, passed, detail

    def record(name, cfg, ok, detail=""):
        results.append({"test": name, "config": cfg, "passed": ok, "detail": detail})
        if verbose and not ok:
            print(f"  FAIL  {name:<22} {cfg:<28} {detail}")

    # ---- assembler encodings
    for src, exp in ENCODINGS.items():
        got = assemble(src).words[0]
        record(f"encode: {src}", "-", got == exp, f"got {got:#010x} expected {exp:#010x}")

    # ---- test programs
    for path in sorted(glob.glob(os.path.join(ASM, "tests", "*.s"))):
        name = os.path.splitext(os.path.basename(path))[0]
        prog = assemble_files([path])
        gbus = Bus(prog)
        g = GoldenCPU(gbus).run()
        if name in EXPECT:
            record(f"{name} (golden answer)", "golden", bool(EXPECT[name](g, gbus, prog)), "wrong result")
        for fw, pol in CONFIGS:
            cfg = f"fwd={'on ' if fw else 'off'} policy={pol}"
            g, gb, p, pb = run_pair(prog, fw, pol)
            probs = compare(g, gb, p, pb)
            s = p.stats()
            ident = s["cycles"] == s["retired"] + 4 + s["data_stalls"] + s["control_penalty"]
            if not ident:
                probs.append("cycle identity violated")
            record(f"{name} (pipe==golden)", cfg, not probs, "; ".join(probs))

    # ---- firmware images under several sensor inputs
    images = {
        "boot+handler": assemble_files([f"{ASM}/common.s", f"{ASM}/boot.s", f"{ASM}/handler.s"], DEFINES),
        "poll+handler (validating)": assemble_files([f"{ASM}/common.s", f"{ASM}/poll.s", f"{ASM}/handler.s"], DEFINES),
        "poll+handler (naive)": assemble_files([f"{ASM}/common.s", f"{ASM}/poll.s", f"{ASM}/handler.s"],
                                               {**DEFINES, "REQUIRE_SMOKE": 0}),
    }
    for iname, prog in images.items():
        for temp, smoke in [(25, 3), (65, 5), (62, 45), (150, 80), (300, 100), (0, 0)]:
            for fw, pol in CONFIGS:
                cfg = f"T={temp},S={smoke} fwd={'on ' if fw else 'off'} {pol}"
                g, gb, p, pb = run_pair(prog, fw, pol, temp, smoke)
                probs = compare(g, gb, p, pb)
                if not (g.slept and p.slept):
                    probs.append("did not reach SLEEP")
                record(f"firmware {iname}", cfg, not probs, "; ".join(probs))

    # ---- behavioural sanity of the validating poll vs. the handler
    prog = images["poll+handler (validating)"]
    for temp, smoke, expect_tx in [(25, 3, False), (65, 5, False), (62, 45, True), (60, 99, False)]:
        g, gb, p, pb = run_pair(prog, True, "not_taken", temp, smoke)
        record("poll decision", f"T={temp},S={smoke}", bool(pb.radio_log) == expect_tx,
               f"tx={bool(pb.radio_log)} expected {expect_tx}")

    passed = sum(r["passed"] for r in results)
    if verbose:
        print(f"{passed}/{len(results)} checks passed")
    return results, passed == len(results)


if __name__ == "__main__":
    _, ok = run_all()
    sys.exit(0 if ok else 1)
