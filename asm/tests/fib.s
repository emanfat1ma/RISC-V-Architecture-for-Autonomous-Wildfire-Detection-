# fib.s - iterative Fibonacci, F(20) = 6765 ends up in t0 (ALU chains + loop branch)
    li   t0, 0
    li   t1, 1
    li   t2, 20
fib_loop:
    add  t3, t0, t1
    mv   t0, t1
    mv   t1, t3
    addi t2, t2, -1
    bnez t2, fib_loop
    ecall
