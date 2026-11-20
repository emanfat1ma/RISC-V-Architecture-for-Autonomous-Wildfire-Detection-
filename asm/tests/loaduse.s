# loaduse.s - array sum where each loaded value is used immediately (load-use hazard)
.data
arr:    .word 5, 10, 15, 20, 25, 30, 35, 40
result: .word 0
.text
    la   t0, arr
    li   t1, 8
    li   t2, 0
lu_loop:
    lw   t3, 0(t0)
    add  t2, t2, t3        # load-use: needs 1 stall cycle
    addi t0, t0, 4
    addi t1, t1, -1
    bnez t1, lu_loop
    la   t4, result
    sw   t2, 0(t4)
    lw   t5, 0(t4)
    addi t5, t5, 1
    ecall
