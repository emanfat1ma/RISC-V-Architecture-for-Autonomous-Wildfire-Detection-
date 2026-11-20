# raw_chain.s - back-to-back RAW dependences (stresses forwarding)
    li   t0, 1
    add  t1, t0, t0
    add  t2, t1, t0
    add  t3, t2, t1
    add  t4, t3, t2
    add  t5, t4, t3
    add  t6, t5, t4
    add  s0, t6, t5
    add  s1, s0, t6
    ecall
