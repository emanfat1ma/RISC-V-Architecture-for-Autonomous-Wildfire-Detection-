# branches.s - alternating (hard to predict) branch inside a counted loop
    li   t0, 0
    li   t1, 40
    li   t2, 0
br_loop:
    andi t3, t0, 1
    beqz t3, br_even        # taken every other iteration
    addi t2, t2, 1
br_even:
    addi t0, t0, 1
    blt  t0, t1, br_loop    # taken 39 times, not taken once (easy to predict)
    ecall
