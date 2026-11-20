# call.s - jal / jalr (function call and return): triangular numbers
    li   a0, 5
    jal  ra, tri
    mv   s0, a0             # 15
    li   a0, 10
    jal  ra, tri
    mv   s1, a0             # 55
    ecall
tri:
    li   t0, 0
    li   t1, 1
tri_loop:
    bgt  t1, a0, tri_done
    add  t0, t0, t1
    addi t1, t1, 1
    j    tri_loop
tri_done:
    mv   a0, t0
    ret
