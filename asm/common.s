# common.s - constants shared by all firmware images (memory map of the SoC)
# TEMP_THRESH, SMOKE_THRESH and REQUIRE_SMOKE are injected by the simulator from config.py
.equ MMIO,      0x40000000      # MMIO base
.equ REG_TEMP,  0               # offsets from MMIO
.equ REG_SMOKE, 4
.equ REG_RADIO, 8
.equ REG_SLEEP, 12
.equ PKT_BASE,  0x10000100      # 16-word scratch / packet buffer in data RAM
.equ STACK_TOP, 0x10000FF0
.equ MAGIC,     0xF1AE          # packet header
