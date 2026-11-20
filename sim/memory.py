"""
memory.py - System bus: instruction memory, data RAM and memory-mapped I/O (MMIO).

Memory map
  0x0000_0000  IMEM  (program, read-only to the core)
  0x1000_0000  DMEM  (4 KiB data RAM; .data section is loaded at the start)
  0x4000_0000  MMIO  TEMP   (R) latest temperature sample, degrees C
  0x4000_0004        SMOKE  (R) latest smoke index (0..100)
  0x4000_0008        RADIO  (W) radio TX FIFO - every word written is logged
  0x4000_000C        SLEEP  (W) writing 1 acknowledges WAKE_UP and requests power-gating
"""
from .isa import M32, NOP

IMEM_BASE = 0x0000_0000
DMEM_BASE = 0x1000_0000
DMEM_SIZE = 0x1000
MMIO_BASE = 0x4000_0000
MMIO_SIZE = 0x100

REG_TEMP = MMIO_BASE + 0x00
REG_SMOKE = MMIO_BASE + 0x04
REG_RADIO = MMIO_BASE + 0x08
REG_SLEEP = MMIO_BASE + 0x0C


class MemoryFault(Exception):
    pass


class Bus:
    def __init__(self, program=None, temp=0, smoke=0):
        self.imem = list(program.words) if program is not None else []
        self.dmem = bytearray(DMEM_SIZE)
        if program is not None:
            for i, w in enumerate(program.data):
                self.dmem[4 * i:4 * i + 4] = (w & M32).to_bytes(4, "little")
        self.temp, self.smoke = temp, smoke
        self.radio_log = []   # (cycle, word)
        self.mmio_log = []    # (addr, value) - every MMIO write, used for verification
        self.sleep_req = False

    # ---- instruction fetch
    def fetch(self, pc, speculative=False):
        if pc & 3:
            raise MemoryFault(f"misaligned fetch {pc:#x}")
        idx = (pc - IMEM_BASE) >> 2
        if 0 <= idx < len(self.imem):
            return self.imem[idx]
        if speculative:           # wrong-path fetch past the end of the program
            return NOP
        raise MemoryFault(f"instruction fetch outside IMEM: {pc:#x}")

    # ---- data side
    def load_word(self, addr):
        addr &= M32
        if addr & 3:
            raise MemoryFault(f"misaligned load {addr:#x}")
        if DMEM_BASE <= addr < DMEM_BASE + DMEM_SIZE:
            o = addr - DMEM_BASE
            return int.from_bytes(self.dmem[o:o + 4], "little")
        if addr == REG_TEMP:
            return self.temp & M32
        if addr == REG_SMOKE:
            return self.smoke & M32
        if MMIO_BASE <= addr < MMIO_BASE + MMIO_SIZE:
            return 0
        raise MemoryFault(f"load from unmapped address {addr:#x}")

    def store_word(self, addr, val, cycle=0):
        addr &= M32
        val &= M32
        if addr & 3:
            raise MemoryFault(f"misaligned store {addr:#x}")
        if DMEM_BASE <= addr < DMEM_BASE + DMEM_SIZE:
            o = addr - DMEM_BASE
            self.dmem[o:o + 4] = val.to_bytes(4, "little")
            return
        if MMIO_BASE <= addr < MMIO_BASE + MMIO_SIZE:
            self.mmio_log.append((addr, val))
            if addr == REG_RADIO:
                self.radio_log.append((cycle, val))
            elif addr == REG_SLEEP and (val & 1):
                self.sleep_req = True
            return
        raise MemoryFault(f"store to unmapped address {addr:#x}")
