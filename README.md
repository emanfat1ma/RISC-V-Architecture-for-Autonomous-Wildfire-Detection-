# Wildfire Detection SoC on RISC-V

CS339 Computer Architecture project (NUST SEECS, BSCS-14D). A software-only simulation of an event-driven, power-gated RISC-V wildfire sensor node, with a dashboard that replays it.

## 1. The idea in one paragraph

A normal forest sensor wakes its CPU every minute to look for fire, and almost every wake-up finds nothing, so the battery drains for no reason. This project keeps the CPU **completely off** and lets two tiny always-on blocks watch the sensors:

- **Tier 1 (sentry):** flags temperature above a limit (default 60 °C).
- **Tier 2 (controller):** requires temperature **and** smoke (default 30) to stay high for N samples in a row (default 5). Only then it asserts `WAKE_UP`.
- **Tier 3 (brain):** a pipelined RV32I core, power-gated until woken. It cold-boots, reads the sensors, scores the severity (class 0 to 3), builds a 4-word packet plus a checksum word, sends it to the radio FIFO, then writes the SLEEP register so the SoC power-gates it again.

The simulator compares this against a conventional node that polls every 60 s, on identical sensor streams. Tier 1 and Tier 2 are separate from the CPU, and the CPU does not confirm the fire: Tier 2 already did.

## 2. Quick start

```
pip install matplotlib streamlit pandas
python main.py test                 # 177 verification checks
python main.py experiments          # regenerates results/ (add --quick for fewer seeds)
python main.py soc --scenario wildfire
python main.py firmware event --sensors 65,45 --trace 40
streamlit run app.py                # the dashboard (developed on Streamlit 1.62.0)
```

Run everything from the project root (where `main.py` lives).

Tested environment: Python 3.11 and Streamlit 1.62.0. The dashboard uses newer Streamlit features (`st.segmented_control`, `st.popover`, horizontal `st.bar_chart`, `vertical_alignment` in columns), so an old Streamlit will fail.

### Installing the dashboard into an existing project
1. Back up your project folder (or rename the old `app.py` to `app_old.py`).
2. Copy these files into the project root, next to `main.py`: `app.py`, `sidebar_controls.py`, `mission_control.py`, `cpu_view.py`, `pipeline_view.py`, `stats_tab.py`, `results_tab.py`.
3. Run `streamlit run app.py`.

`app.py` imports all the other dashboard files. If you only replace some of them, mixed versions can fail, so copy the full set.

## 3. Project layout

| Path | Purpose |
|---|---|
| `main.py`, `config.py`, `experiments.py` | Command line, all parameters, experiments |
| `sim/` | isa, assembler, memory, golden model, 5-stage pipeline, sensors, tiers, energy, soc |
| `asm/` | Firmware (`common.s`, `boot.s`, `handler.s`, `poll.s`) and `tests/*.s` |
| `tests/run_tests.py` | Verification suite |
| `results/` | Generated CSV tables, plots and pipeline traces |
| `app.py` | Dashboard entry point: 4 tabs, shared state |
| `sidebar_controls.py` | Controls panel (scenario, presets, advanced, power assumptions) |
| `mission_control.py` | Animated replay: banner, forest scene, tier diagram, twin nodes, feed, sound, verdict cards |
| `cpu_view.py` | RISC-V tab: firmware steps, conveyor belt, boot cost, packet, CPI bars |
| `pipeline_view.py` | Colour-coded pipeline grid from the trace text (stalls, flushes, forwarding) |
| `stats_tab.py` | Many-seed statistics and battery life with self-discharge |
| `results_tab.py` | "Evidence for the report" tab |

## 4. What is implemented

### 4.1 Simulator (original project)
- RV32I subset, two-pass assembler, golden (non-pipelined) model.
- Cycle-accurate 5-stage pipeline: forwarding (on/off), load-use stall, three branch policies (`stall`, `not_taken`, `bimodal`), performance counters, per-cycle trace.
- Firmware: cold-boot ROM, alert handler, polling node (naive and validated).
- Behavioural Tier 1 and Tier 2, synthetic sensors (normal, heatwave, wildfire) with glitches.
- Energy model driven by the **measured** core cycles, deployment-mix averages, sweeps, sensitivity analysis.
- 177 automated checks (assembler, golden model, pipeline vs golden, firmware, polling decisions).

### 4.2 Dashboard (added)
- **Sidebar:** scenario, Sensitive / Balanced / Strict presets, polling-period chips, advanced sliders, power assumptions (flagged as needing datasheet sources). Power edits re-cost the saved run instantly.
- **Mission control:** replay of the real simulated day with event-aware speed (fast through quiet hours, slow near ignition and alerts), Next event, speed menu and scrubber. Status banner with persistence ring, forest scene, live Tier 1/2/3 diagram with wake pulse, sensor meters, twin nodes (event-driven vs validated polling: wake-ups and energy so far), activity feed, four verdict cards. Optional sound: siren (real fire), chirp (re-alert), two-note tone (polling alert), buzz (false alert). Click **Enable sound** once; browsers block autoplay.
- **RISC-V core:** pick a firmware and sensor values, see cycles, instructions, CPI, a conveyor-belt view of the real trace (stalls, flushes, held fetches), seven clickable firmware steps (boot, read sensors, score, classify, build packet, send, sleep) located by real instruction addresses, boot-versus-alert cost, the radio packet, and six-setting CPI bars. Benchmark programs are checked against the golden model, with the colour-coded grid.
- **Statistics & battery:** many seeds per scenario: missed fires (one dot per day), detection time, false alerts per heatwave day, and battery life as stacked bars (node draw against battery self-discharge).
- **Saved results ("Results for your report"):** a curated list in report order (8.1 to 8.6, correctness checks, pipeline step logs) on the left and one result at a time on the right. Each result shows a plain-English description, a takeaway quoted from the report, the large figure, download buttons (PNG, CSV), a collapsed data table and a suggested caption. The 177-check status and generated time sit in the header. Refresh results (with a confirmation) reruns the experiments. Files not in the curated list are tucked into "Other files".

## 5. How numbers flow

`config.py` → `sim/sensors.py` (stream) → `sim/soc.py` (Tier 1/2 + real firmware on the pipeline) → activity summary → `sim/energy.py` (cost). `app.py` caches the run, and each tab only displays results from it. Changing a sidebar power value re-costs without re-simulating.

## 6. Verification status

### Checked
- The 177-check suite is reported passing in the project report. It was not re-run while building the dashboard, so run `python main.py test` before submission.
- Firmware run (TEMP 65, SMOKE 45): 171 cycles, 123 instructions, CPI 1.39, matching the report's ranges. The radio packet `0xf1ae, 0x41, 0x2d, 0x1, 0xf21d` agrees with `handler.s`: 0x41 = 65, 0x2d = 45, class 1 (score (65-60)/8 + 45/8 = 5), and the checksum equals the sum of the four words.
- Instruction split from reading the source: about 70 in boot and about 53 in the handler, which adds to 123.
- Battery arithmetic reproduced independently: 32,400 J cell, 2,276 / 267 / 277 years without self-discharge, 49 / 42 / 42 years at 2% a year, 20.5 µW leak.
- Normal-day energy reproduced: event-driven 21.5 mJ (83 nA × 3 V × 24 h); polling about 303 mJ.
- All dashboard Python files compile.

### Not yet verified
- The dashboard has not been run in a browser. Layout, animation, sound and Streamlit behaviour are untested.
- Dashboard numbers should match `python main.py soc --scenario <x> --seed <n>` for the same settings. Compare once.
- `results_tab.py` guesses the pass/fail column of `verification.csv` (names such as passed, ok, result, status). If the badge says "checks listed" instead of "checks passed", the column name was not recognised: send the header row.
- The Saved results tab uses plain Streamlit widgets (radio list, bordered container, popover). Its takeaways are quoted from the report's Section 8 and the captions are suggestions, so check both against your final results. Item names assume the file names in `results/` shown in this project (pipeline_cpi, scenario_summary, sweeps, sensitivity, cold_start, lifetime, poll_period_sweep, verification).
- Forwarding highlights in the pipeline grid are inferred from register names in the trace, not read from the forwarding unit.
- The firmware-step chips apply to the event firmware only. `poll.s` has no step mapping.
- Plot captions and "Report 8.x" tags in the results tab are my wording, so check them against the actual plots.
- All design mock-ups used sample numbers where they say so.

## 7. What is left

**Required for credibility**
1. Replace every assumed power number with a cited datasheet value (sleep current, active current, radio, sensor, battery self-discharge) and list the sources in the report.
2. Re-run `python main.py test` and `python main.py experiments` for fresh results.
3. Run the dashboard once end to end and fix anything broken.
4. Record the demo (see section 9).

**Gaps against the full wish-list**
- Tier 2 as an explicit state machine (IDLE, SUSPECT, VALIDATING, CONFIRMED, WAKE, COOLDOWN) with a diagram.
- Tier 1 hysteresis and a threshold-crossing counter; separate Tier 1 and Tier 2 energy lines.
- Explicit power states (ACTIVE, DOZE, SLEEP, POWER-GATED) with timeline and a wake-latency parameter.
- Radio packet loss and retries, with a retries-versus-energy experiment.
- More scenarios: rapid and slow-onset fire, smoke-only disturbance, multiple fires.
- Statistics: confidence intervals; precision, recall and F1.
- Tests for Tier 1/2 behaviour, duplicate suppression, energy accounting and radio retry.
- Optional extension: a small instruction cache to model cold misses after each wake.

**Dashboard polish**
- A "nothing to report yet" placeholder in Node activity on quiet days.
- Replace `st.components.v1.html` with `st.iframe` when upgrading Streamlit (the old call still works in 1.62.0 with a warning).
- Pause or scrub markers for events on the playback bar.
- Check the Saved results layout in the browser and adjust spacing if needed.

## 8. Limitations
- Simulation only: no RTL, no physical measurements. Tier 1 and Tier 2 are behavioural models.
- Sensor data is synthetic.
- All power values are assumptions until cited, so read the results as energy ratios. The 14× normal-day ratio depends mainly on the sleep floor and sensor sampling, not on the CPU (see the sensitivity table).
- Battery lifetime without self-discharge is not physically meaningful.
- The core has no caches, M extension, byte or halfword accesses, interrupts, exceptions or CSRs.
- The CPU's energy is tiny next to the radio. The pipeline matters for the architecture goals and for measuring the wake cost, not for the headline saving.

## 9. Demo order (about 9 minutes)
1. Show `python main.py test` passing.
2. Normal day: no wake-ups, 14× less energy.
3. Heatwave: Tier 1 trips, Tier 2 says no; then persistence 1 and smoke 10 to cause false alerts.
4. Wildfire: Next event, siren about 13 s after ignition, later polling tone.
5. RISC-V tab: boot, send loop with its load-use stall, flushes, forwarding on and off.
6. Statistics: missed fires, false alerts, battery with the self-discharge slider.
7. State the limitations honestly.

## 10. Troubleshooting
- **`ModuleNotFoundError`:** install missing packages and run from the project root.
- **Blank widget:** open the browser console (F12) and send the first red error.
- **No sound:** click Enable sound first, and check the tab is not muted.
- **Slow first load:** it assembles firmware and simulates a whole day. Later changes to power assumptions are instant.
- **Statistics run is slow:** reduce seeds per scenario.
- **Deprecation warnings** about `use_container_width` or `components.html`: harmless in 1.62.0.

## 11. Glossary
- **Tick or cycle:** one beat of the CPU clock (1 µs at 1 MHz).
- **CPI:** clock cycles per instruction (lower is better).
- **Stall:** a pipeline bubble while waiting for a result. **Flush:** wrong-path instructions thrown away after a taken branch.
- **Forwarding:** passing a result straight to a later stage so it need not wait.
- **Power gating:** switching the CPU's supply off, so it loses all state and must cold-boot.
- **Hold-off:** time Tier 2 stays disarmed after an alert (default 300 s).
- **Self-discharge:** charge a battery loses by itself each year (assumed 2%).