# arith.s - exercises every ALU instruction
    li   t0, 15
    li   t1, 7
    add  t2, t0, t1        # 22
    sub  t3, t0, t1        # 8
    and  t4, t0, t1        # 7
    or   t5, t0, t1        # 15
    xor  t6, t0, t1        # 8
    slli s0, t0, 4         # 240
    srli s1, s0, 2         # 60
    li   s2, -16
    srai s3, s2, 2         # -4
    srli s4, s2, 28        # 15
    slt  s5, s2, t0        # 1  (signed)
    sltu s6, s2, t0        # 0  (unsigned)
    lui  s7, 0x12345
    addi s7, s7, 0x678     # 0x12345678
    li   s8, 0x7FFFFFFF
    addi s8, s8, 1         # wraps to 0x80000000
    li   s9, 100000        # needs lui + addi
    xori s10, t0, 5        # 10
    andi s11, t0, 6        # 6
    ecall
