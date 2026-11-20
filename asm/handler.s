# handler.s - wildfire event handler (runs on the RISC-V core after a validated WAKE_UP)
#   1. read temperature + smoke from MMIO
#   2. compute a severity score and classify it (0 low .. 3 critical)
#   3. build a 4-word packet in RAM, checksum it while streaming it to the radio FIFO
#   4. acknowledge by writing SLEEP -> the SoC power-gates the core again
handler_main:
    li   s0, MMIO
    lw   t0, REG_TEMP(s0)       # temperature (deg C)
    lw   t1, REG_SMOKE(s0)      # smoke index 0..100

    li   t2, TEMP_THRESH
    sub  t3, t0, t2             # temperature excess over threshold
    bge  t3, zero, hd_t_ok
    li   t3, 0                  # clamp negative excess to 0
hd_t_ok:
    srli t3, t3, 3              # excess / 8
    srli t4, t1, 3              # smoke / 8
    add  t5, t3, t4             # severity score

    li   a0, 0                  # class 0 : score < 4
    li   t6, 4
    blt  t5, t6, hd_class_done
    li   a0, 1                  # class 1 : score < 8
    li   t6, 8
    blt  t5, t6, hd_class_done
    li   a0, 2                  # class 2 : score < 16
    li   t6, 16
    blt  t5, t6, hd_class_done
    li   a0, 3                  # class 3 : critical
hd_class_done:
    li   s1, PKT_BASE           # packet = [MAGIC, temp, smoke, class]
    li   t6, MAGIC
    sw   t6, 0(s1)
    sw   t0, 4(s1)
    sw   t1, 8(s1)
    sw   a0, 12(s1)

    li   a1, 0                  # checksum
    li   a2, 4                  # words left
    mv   a3, s1
hd_tx_loop:
    lw   t6, 0(a3)
    add  a1, a1, t6             # load-use hazard (needs a stall even with forwarding)
    sw   t6, REG_RADIO(s0)      # push word to radio FIFO
    addi a3, a3, 4
    addi a2, a2, -1
    bnez a2, hd_tx_loop
    sw   a1, REG_RADIO(s0)      # checksum word
    li   t6, 1
    sw   t6, REG_SLEEP(s0)      # request power-gate
hd_hang:
    j    hd_hang
