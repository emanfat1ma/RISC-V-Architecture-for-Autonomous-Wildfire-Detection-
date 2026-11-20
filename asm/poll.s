# poll.s - conventional polling node: woken by a timer every 60 s, it samples the
# sensors and decides in SOFTWARE whether there is an event. No hardware filter.
#   REQUIRE_SMOKE = 0 : naive node, transmits whenever temperature > TEMP_THRESH
#   REQUIRE_SMOKE = 1 : validating node, also requires smoke >= SMOKE_THRESH
# (state is retained in low-power sleep, so there is no cold-boot sequence)
poll_main:
    li   a0, MMIO
    lw   t0, REG_TEMP(a0)
    lw   t1, REG_SMOKE(a0)
    li   t2, TEMP_THRESH
    ble  t0, t2, poll_done      # temperature not above threshold -> nothing to do
    li   t3, REQUIRE_SMOKE
    beqz t3, poll_alert         # naive node: temperature alone triggers an alert
    li   t2, SMOKE_THRESH
    blt  t1, t2, poll_done      # validating node: smoke too low -> reject
poll_alert:
    j    handler_main           # reuse the same alert handler
poll_done:
    li   t4, 1
    sw   t4, REG_SLEEP(a0)
poll_hang:
    j    poll_hang
