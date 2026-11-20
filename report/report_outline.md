# Report outline (map each section to generated artefacts)

1. **Abstract / Introduction** - problem: idle CPU polling drains batteries; idea: filter events in hardware, wake a RISC-V core only for validated events.
2. **System architecture** - 3 tiers, memory map, wake/sleep protocol. (redraw your Fig. 1/2)
3. **RISC-V core design** - ISA subset (`sim/isa.py`), 5-stage pipeline, forwarding, hazard unit, branch policies.
   * Figures: `results/trace_loaduse_forwarding.txt`, `trace_raw_chain_forwarding_on/off.txt`, `trace_branches_bimodal.txt`
4. **Software / firmware** - `asm/boot.s`, `asm/handler.s`, `asm/poll.s`; assembler.
5. **Verification** - golden model vs pipeline, 177 checks (`results/verification.csv`).
6. **Pipeline results** - `results/pipeline_cpi.csv/.png`: forwarding on/off, branch policies, CPI breakdown (stalls, flush penalty).
7. **Cold-start cost of power gating** - `results/cold_start.csv` (boot cycles, WAKE_UP -> radio write latency).
8. **System results** - `scenario_summary.csv/.png`: energy/day, wake-ups, false alarms, latency for normal / heatwave / wildfire.
9. **Design-space sweeps** - persistence, smoke and temperature thresholds (`sweeps.csv/.png`); polling period trade-off (`poll_period_sweep.csv`).
10. **Sensitivity & limitations** - `sensitivity.csv/.png`; synthetic data; assumed power numbers; no self-discharge; no real analog behaviour.
11. **Conclusion & future work** - cache, better predictors, ISA extension.
12. **References** - RISC-V spec; datasheets used for every `config.py` power parameter; Patterson & Hennessy (pipelining).
