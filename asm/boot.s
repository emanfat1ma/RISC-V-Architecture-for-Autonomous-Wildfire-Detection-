# boot.s - cold-boot ROM. The RISC-V core is power-gated, so on WAKE_UP all registers
# and the pipeline are blank. Boot sets up the stack, clears the packet scratch
# buffer, then jumps to the event handler. Its length is the "cold-boot penalty".
boot:
    li   sp, STACK_TOP
    li   t0, PKT_BASE
    li   t1, 16                 # clear 16 words of scratch RAM
boot_clear:
    sw   zero, 0(t0)
    addi t0, t0, 4
    addi t1, t1, -1
    bnez t1, boot_clear
    j    handler_main
