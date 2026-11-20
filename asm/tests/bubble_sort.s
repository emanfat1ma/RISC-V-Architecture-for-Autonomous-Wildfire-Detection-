# bubble_sort.s - sorts 12 words in place (loads, stores, data-dependent branches)
.data
vals: .word 9, 3, 7, 1, 8, 2, 6, 5, 4, 0, 11, 10
.text
    la   s0, vals
    li   s1, 12
bs_outer:
    li   t0, 0              # swapped = 0
    li   t1, 1              # i = 1
    mv   t2, s0
bs_inner:
    bge  t1, s1, bs_inner_done
    lw   t3, 0(t2)
    lw   t4, 4(t2)
    ble  t3, t4, bs_no_swap
    sw   t4, 0(t2)
    sw   t3, 4(t2)
    li   t0, 1
bs_no_swap:
    addi t2, t2, 4
    addi t1, t1, 1
    j    bs_inner
bs_inner_done:
    bnez t0, bs_outer
    ecall
