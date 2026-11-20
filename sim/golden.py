"""
golden.py - Simple, non-pipelined ISA-level simulator (the "golden model").

One instruction per step, no timing detail. It defines the *correct architectural
behaviour*; the pipelined core must end every program in exactly the same state.
"""
from .isa import M32, alu, branch_taken, decode, exec_result


class GoldenCPU:
    def __init__(self, bus):
        self.bus = bus
        self.regs = [0] * 32
        self.pc = 0
        self.retired = 0
        self.halted = False     # ecall executed
        self.slept = False      # SLEEP register written (power-gate request)

    @property
    def cycles(self):
        return self.retired     # ideal single-cycle machine: CPI = 1

    def _write(self, rd, val):
        if rd != 0:
            self.regs[rd] = val & M32

    def step(self):
        bus, regs = self.bus, self.regs
        pc = self.pc
        d = decode(bus.fetch(pc))
        a, b = regs[d.rs1], regs[d.rs2]
        npc = (pc + 4) & M32

        if d.name == "ecall":
            self.halted = True
        elif d.is_load:
            self._write(d.rd, bus.load_word((a + d.imm) & M32))
        elif d.is_store:
            bus.store_word((a + d.imm) & M32, b, cycle=self.retired)
            if bus.sleep_req:
                self.slept = True
        elif d.is_branch:
            if branch_taken(d.name, a, b):
                npc = (pc + d.imm) & M32
        elif d.is_jal:
            self._write(d.rd, pc + 4)
            npc = (pc + d.imm) & M32
        elif d.is_jalr:
            self._write(d.rd, pc + 4)
            npc = (a + d.imm) & ~1 & M32
        else:
            self._write(d.rd, exec_result(d, a, b, pc))

        self.retired += 1
        self.pc = npc

    def run(self, max_instructions=2_000_000):
        while not (self.halted or self.slept):
            self.step()
            if self.retired > max_instructions:
                raise RuntimeError("golden model: instruction limit exceeded (infinite loop?)")
        return self
