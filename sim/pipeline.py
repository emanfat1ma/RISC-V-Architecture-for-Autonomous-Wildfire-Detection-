"""
pipeline.py - Cycle-accurate 5-stage RV32I pipeline (IF, ID, EX, MEM, WB).

Features (each can be switched for experiments):
  * Data forwarding EX/MEM -> EX and MEM/WB -> EX            (forwarding=True/False)
  * Hazard detection unit: 1-cycle load-use stall; without forwarding, RAW stalls
  * Regfile written in the first half of WB and read in the second half of ID
  * Control hazards, three policies (branch_policy):
        'stall'      - never speculate: every branch costs a 2-cycle bubble
        'not_taken'  - predict not-taken, resolve in EX, flush 2 on a taken branch
        'bimodal'    - 2-bit saturating-counter BHT consulted in ID (1 bubble when
                       predicted taken, up to 2 on a misprediction)
    JAL is redirected in ID (1 bubble); JALR is resolved in EX (2 bubbles).
  * Performance counters: cycles, retired, stalls, flush penalty, forwards, branches...
  * Optional per-cycle trace for pipeline diagrams (trace=True)

Termination: `ecall` (halt, test programs) or a store of 1 to the MMIO SLEEP register
(power-gate request, firmware). The SLEEP store is honoured when it reaches MEM.
"""
from .isa import M32, branch_taken, decode, disasm, exec_result


class Slot:
    """One instruction travelling through the pipeline (acts as the pipeline register)."""
    __slots__ = ("pc", "d", "rs1_val", "rs2_val", "result", "addr", "store_val",
                 "wb_val", "pred_taken")

    def __init__(self, pc, d):
        self.pc, self.d = pc, d
        self.rs1_val = self.rs2_val = self.result = self.addr = 0
        self.store_val = self.wb_val = 0
        self.pred_taken = False


class PipelineCPU:
    POLICIES = ("stall", "not_taken", "bimodal")

    def __init__(self, bus, forwarding=True, branch_policy="not_taken", trace=False,
                 bht_entries=64, watch_pcs=None):
        if branch_policy not in self.POLICIES:
            raise ValueError(f"branch_policy must be one of {self.POLICIES}")
        self.bus = bus
        self.forwarding = forwarding
        self.policy = branch_policy
        self.regs = [0] * 32
        self.pc = 0
        self.if_id = self.id_ex = self.ex_mem = self.mem_wb = None
        self.halting = False     # ecall reached EX: stop fetching, drain
        self.halted = False      # ecall retired
        self.slept = False       # SLEEP store executed in MEM
        self.bht = [1] * bht_entries
        self.watch_pcs = set(watch_pcs or [])
        self.watch_hit = {}      # pc -> cycle at which it first retired
        self.trace_on = trace
        self.trace = []
        # ---- performance counters
        self.cycles = self.retired = 0
        self.data_stalls = 0           # bubbles inserted by the hazard detection unit
        self.control_penalty = 0       # bubbles caused by redirects/flushes
        self.fwd_ex_mem = self.fwd_mem_wb = 0
        self.branches = self.mispredicts = 0
        self.jumps = 0
        self.loads = self.stores = 0

    # ------------------------------------------------------------ helpers
    def _operand(self, reg, used, val, ex_mem, mem_wb):
        """Forwarding unit: pick the newest value of `reg` available to the EX stage."""
        if not used or reg == 0 or not self.forwarding:
            return val
        if ex_mem is not None and ex_mem.d.writes_rd and ex_mem.d.rd == reg:
            assert not ex_mem.d.is_load, "load-use hazard should have been stalled"
            self.fwd_ex_mem += 1
            return ex_mem.result
        if mem_wb is not None and mem_wb.d.writes_rd and mem_wb.d.rd == reg:
            self.fwd_mem_wb += 1
            return mem_wb.wb_val
        return val

    def _hazard(self, s, id_ex, ex_mem):
        """Hazard detection unit (consumer `s` sits in ID)."""
        d = s.d
        srcs = []
        if d.uses_rs1 and d.rs1 != 0:
            srcs.append(d.rs1)
        if d.uses_rs2 and d.rs2 != 0:
            srcs.append(d.rs2)
        if not srcs:
            return False
        if self.forwarding:   # only a load directly ahead cannot be forwarded in time
            return (id_ex is not None and id_ex.d.is_load and id_ex.d.rd != 0
                    and id_ex.d.rd in srcs)
        for p in (id_ex, ex_mem):
            if p is not None and p.d.writes_rd and p.d.rd != 0 and p.d.rd in srcs:
                return True
        return False

    @staticmethod
    def _lbl(slot):
        return "-" if slot is None else f"{slot.pc:03x}:{disasm(slot.d)}"

    # ------------------------------------------------------------ one clock cycle
    def cycle(self):
        bus = self.bus
        self.cycles += 1
        if_id, id_ex, ex_mem, mem_wb = self.if_id, self.id_ex, self.ex_mem, self.mem_wb

        # ---------------- WB
        if mem_wb is not None:
            d = mem_wb.d
            if d.writes_rd and d.rd != 0:
                self.regs[d.rd] = mem_wb.wb_val & M32
            self.retired += 1
            if mem_wb.pc in self.watch_pcs and mem_wb.pc not in self.watch_hit:
                self.watch_hit[mem_wb.pc] = self.cycles
            if d.name == "ecall":
                self.halted = True

        # ---------------- MEM
        new_mem_wb = None
        if ex_mem is not None:
            s, d = ex_mem, ex_mem.d
            if d.is_load:
                s.wb_val = bus.load_word(s.addr)
                self.loads += 1
            elif d.is_store:
                bus.store_word(s.addr, s.store_val, cycle=self.cycles)
                self.stores += 1
                if bus.sleep_req:           # power-gate: everything younger is discarded
                    self.slept = True
                    self.retired += 1
            else:
                s.wb_val = s.result
            new_mem_wb = s

        if self.slept:
            if self.trace_on:
                self.trace.append((self.cycles, "-", "-", "-", self._lbl(ex_mem), self._lbl(mem_wb)))
            return

        # ---------------- EX
        new_ex_mem = None
        redirect = None
        halt_flush = False
        if id_ex is not None:
            s, d = id_ex, id_ex.d
            a = self._operand(d.rs1, d.uses_rs1, s.rs1_val, ex_mem, mem_wb)
            b = self._operand(d.rs2, d.uses_rs2, s.rs2_val, ex_mem, mem_wb)
            if d.name == "ecall":
                halt_flush = True
            elif d.is_load:
                s.addr = (a + d.imm) & M32
            elif d.is_store:
                s.addr = (a + d.imm) & M32
                s.store_val = b
            elif d.is_branch:
                self.branches += 1
                taken = branch_taken(d.name, a, b)
                target = (s.pc + d.imm) & M32
                nxt = target if taken else (s.pc + 4) & M32
                if self.policy == "stall":
                    redirect = nxt
                elif self.policy == "not_taken":
                    if taken:
                        self.mispredicts += 1
                        redirect = target
                else:                                   # bimodal
                    idx = (s.pc >> 2) % len(self.bht)
                    self.bht[idx] = min(3, self.bht[idx] + 1) if taken else max(0, self.bht[idx] - 1)
                    if taken != s.pred_taken:
                        self.mispredicts += 1
                        redirect = nxt
            elif d.is_jalr:
                self.jumps += 1
                s.result = (s.pc + 4) & M32
                redirect = (a + d.imm) & ~1 & M32
            elif d.is_jal:
                s.result = (s.pc + 4) & M32
            else:
                s.result = exec_result(d, a, b, s.pc)
            new_ex_mem = s

        if halt_flush:
            self.halting = True

        # ---------------- ID
        new_id_ex = None
        stall = False
        id_redirect = None
        if if_id is not None and redirect is None and not halt_flush:
            s, d = if_id, if_id.d
            if self._hazard(s, id_ex, ex_mem):
                stall = True
                self.data_stalls += 1
            else:
                s.rs1_val, s.rs2_val = self.regs[d.rs1], self.regs[d.rs2]
                new_id_ex = s
                if d.is_jal:
                    self.jumps += 1
                    id_redirect = (s.pc + d.imm) & M32
                elif d.is_branch and self.policy == "bimodal":
                    if self.bht[(s.pc >> 2) % len(self.bht)] >= 2:
                        s.pred_taken = True
                        id_redirect = (s.pc + d.imm) & M32

        # ---------------- IF
        if_text = "-"
        new_if_id = None
        if halt_flush or self.halting:
            pass
        elif redirect is not None:
            if self.trace_on:
                if_text = "x " + disasm(decode(bus.fetch(self.pc, True)))
            self.pc = redirect
            # wasted slots: the fetch of this cycle, plus the ID slot if it held a real
            # instruction (it may already be a bubble left by an earlier ID redirect)
            self.control_penalty += 1 + (1 if if_id is not None else 0)
        elif stall:
            new_if_id = if_id            # hold IF/ID and PC
            if_text = "(held)"
        elif id_redirect is not None:
            if self.trace_on:
                if_text = "x " + disasm(decode(bus.fetch(self.pc, True)))
            self.pc = id_redirect
            self.control_penalty += 1
        else:
            word = bus.fetch(self.pc, speculative=True)
            new_if_id = Slot(self.pc, decode(word))
            if self.trace_on:
                if_text = f"{self.pc:03x}:{disasm(new_if_id.d)}"
            self.pc = (self.pc + 4) & M32

        if self.trace_on:
            id_text = self._lbl(if_id)
            if redirect is not None or halt_flush:
                id_text = "x " + id_text if if_id is not None else "-"
            elif stall:
                id_text += " (stall)"
            self.trace.append((self.cycles, if_text, id_text, self._lbl(id_ex),
                               self._lbl(ex_mem), self._lbl(mem_wb)))

        self.if_id, self.id_ex, self.ex_mem, self.mem_wb = new_if_id, new_id_ex, new_ex_mem, new_mem_wb

    # ------------------------------------------------------------ run / report
    def run(self, max_cycles=2_000_000):
        while not (self.halted or self.slept):
            self.cycle()
            if self.cycles > max_cycles:
                raise RuntimeError("pipeline: cycle limit exceeded (infinite loop?)")
        return self

    def stats(self):
        return {
            "cycles": self.cycles, "retired": self.retired,
            "cpi": self.cycles / self.retired if self.retired else float("nan"),
            "data_stalls": self.data_stalls, "control_penalty": self.control_penalty,
            "fwd_ex_mem": self.fwd_ex_mem, "fwd_mem_wb": self.fwd_mem_wb,
            "branches": self.branches, "mispredicts": self.mispredicts, "jumps": self.jumps,
            "loads": self.loads, "stores": self.stores,
        }

    def format_trace(self, max_rows=None):
        hdr = ("cycle", "IF", "ID", "EX", "MEM", "WB")
        rows = self.trace[:max_rows] if max_rows else self.trace
        widths = [max(len(str(r[i])) for r in rows + [hdr]) for i in range(6)]
        fmt = "  ".join(f"{{:<{w}}}" for w in widths)
        out = [fmt.format(*hdr), fmt.format(*["-" * w for w in widths])]
        out += [fmt.format(*[str(c) for c in r]) for r in rows]
        return "\n".join(out)
