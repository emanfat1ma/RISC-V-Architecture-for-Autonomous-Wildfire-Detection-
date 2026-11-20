# memcpy.s - copy 16 words and checksum them (load/store heavy)
.data
src: .word 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16
dst: .word 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
.text
    la   t0, src
    la   t1, dst
    li   t2, 16
    li   s0, 0
mc_loop:
    lw   t3, 0(t0)
    sw   t3, 0(t1)
    add  s0, s0, t3
    addi t0, t0, 4
    addi t1, t1, 4
    addi t2, t2, -1
    bnez t2, mc_loop
    ecall
