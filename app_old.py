"""Streamlit dashboard for the wildfire RISC-V SoC project (uses the real sim/ modules).

Place this file in the project root, next to main.py, then:
    pip install streamlit
    streamlit run app.py
"""
import glob
import os
import sys

import numpy as np
import streamlit as st
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from config import CONFIG, make_config
from sim.assembler import assemble_files
from sim.golden import GoldenCPU
from sim.memory import Bus
from sim.pipeline import PipelineCPU
from sim.sensors import generate
from sim.soc import ASM_DIR, WildfireSoC
from sim.tiers import Tier1
from pipeline_view import show_pipeline
from stats_tab import show_stats

LABELS = {"event": "Event-driven",
          "polling_naive": "Polling (naive)",
          "polling_validated": "Polling (validated)"}
TEST_DEFS = {"TEMP_THRESH": 60, "SMOKE_THRESH": 30, "REQUIRE_SMOKE": 1}


# ------------------------------------------------------------------ cached simulation
@st.cache_resource(show_spinner="Assembling firmware...")
def get_soc(temp_c, smoke, persist, hold, poll_s, fwd, policy):
    cfg = make_config(thresholds={"temp_c": temp_c, "smoke": smoke},
                      tier2={"persistence": persist, "rearm_holdoff_s": hold},
                      poll={"period_s": poll_s},
                      cpu={"forwarding": fwd, "branch_policy": policy})
    return WildfireSoC(cfg)


@st.cache_resource(show_spinner="Generating sensor data...")
def get_stream(scenario, seed):
    return generate(scenario, CONFIG["duration_s"], CONFIG["sample_period_s"], seed)


@st.cache_resource(show_spinner="Simulating all three designs (runs the real RISC-V core)...")
def get_activity(scenario, seed, temp_c, smoke, persist, hold, poll_s, fwd, policy):
    soc = get_soc(temp_c, smoke, persist, hold, poll_s, fwd, policy)
    stream = get_stream(scenario, seed)
    return {m: soc.simulate(m, stream) for m in WildfireSoC.MODES}


def run_fw(prog, t, s, fwd, policy, trace=False):
    bus = Bus(prog, t, s)
    cpu = PipelineCPU(bus, forwarding=fwd, branch_policy=policy, trace=trace).run()
    return cpu, bus


# ------------------------------------------------------------------ page + sidebar
st.set_page_config(page_title="Wildfire RISC-V SoC", layout="wide")
st.title("Event-driven RISC-V wildfire node: simulator dashboard")

with st.sidebar:
    st.header("Scenario")
    scenario = st.selectbox("Scenario", ["normal", "heatwave", "wildfire"], index=2)
    seed = st.number_input("Random seed", 0, 9999, CONFIG["seed"])

    st.header("Tier 1 / Tier 2")
    T = st.slider("Temperature threshold (°C)", 30, 100, CONFIG["thresholds"]["temp_c"])
    S = st.slider("Smoke threshold", 5, 80, CONFIG["thresholds"]["smoke"])
    persist = st.slider("Persistence (samples)", 1, 20, CONFIG["tier2"]["persistence"])
    hold = st.slider("Re-arm hold-off (s)", 0, 900, CONFIG["tier2"]["rearm_holdoff_s"], step=30)

    st.header("Conventional baseline")
    poll_s = st.select_slider("Polling period (s)", [10, 30, 60, 120, 300],
                              value=CONFIG["poll"]["period_s"])

    st.header("RISC-V core")
    fwd = st.checkbox("Forwarding", CONFIG["cpu"]["forwarding"])
    policy = st.selectbox("Branch policy", list(PipelineCPU.POLICIES),
                          index=list(PipelineCPU.POLICIES).index(CONFIG["cpu"]["branch_policy"]))

    with st.expander("Power assumptions (re-costs instantly)"):
        P0 = CONFIG["power"]
        sleep_ua = st.number_input("Baseline sleep current (µA)", 0.0, 50.0, P0["baseline_sleep_current_a"] * 1e6, 0.1)
        t1_na = st.number_input("Tier 1 current (nA)", 0.0, 1000.0, P0["tier1_current_a"] * 1e9, 1.0)
        t2_na = st.number_input("Tier 2 current (nA)", 0.0, 1000.0, P0["tier2_current_a"] * 1e9, 1.0)
        leak_na = st.number_input("Gated-core leakage (nA)", 0.0, 1000.0, P0["gated_core_leakage_a"] * 1e9, 1.0)
        samp_uj = st.number_input("Sensor sample energy (µJ)", 0.0, 500.0, P0["sensor_sample_energy_j"] * 1e6, 1.0)
        rad_ma = st.number_input("Radio TX current (mA)", 0.0, 500.0, P0["radio_tx_current_a"] * 1e3, 1.0)
        rad_s = st.number_input("Radio air time (s)", 0.0, 5.0, P0["radio_tx_time_s"], 0.05)

cost_cfg = make_config(power={
    "baseline_sleep_current_a": sleep_ua * 1e-6, "tier1_current_a": t1_na * 1e-9,
    "tier2_current_a": t2_na * 1e-9, "gated_core_leakage_a": leak_na * 1e-9,
    "sensor_sample_energy_j": samp_uj * 1e-6, "radio_tx_current_a": rad_ma * 1e-3,
    "radio_tx_time_s": rad_s})

params = (T, S, persist, hold, poll_s, fwd, policy)
soc = get_soc(*params)
stream = get_stream(scenario, int(seed))
acts = get_activity(scenario, int(seed), *params)
summ = {m: soc.summarize(acts[m], cost_cfg) for m in WildfireSoC.MODES}

tab1, tab2, tab3, tab4 = st.tabs(["System simulation", "RISC-V core", "Saved results", "Statistics & battery"])

# ================================================================== TAB 1
with tab1:
    from mission_control import show_mission
    show_mission(stream, acts, summ, T, S, persist, hold, poll_s)
    for col, m in zip(st.columns(3), WildfireSoC.MODES):
        r = summ[m]
        with col:
            st.subheader(LABELS[m])
            st.metric("Energy per day", f"{r['energy_j'] * 1e3:.1f} mJ")
            st.caption(f"{r['avg_power_uw']:.2f} µW average power")
            st.write(f"**CPU wake-ups:** {r['core_wakeups']}")
            st.write(f"**Transmissions:** {r['transmissions']} (false: {r['false_transmissions']})")
            if r["missed_fire"] is not None:
                if r["missed_fire"]:
                    st.error("Fire MISSED")
                else:
                    st.write(f"**Detection latency:** {r['latency_s']:.1f} s")
            if m == "event" and r["core_wakeups"]:
                st.caption(f"Each wake runs ~{r['avg_cycles_per_wake']:.0f} cycles (measured on the pipeline)")

    e_ev = summ["event"]["energy_j"]
    st.info(f"Polling (validated) uses **{summ['polling_validated']['energy_j'] / e_ev:.1f}x** and "
            f"polling (naive) **{summ['polling_naive']['energy_j'] / e_ev:.1f}x** the energy of the "
            f"event-driven design in this run.")

    # ---- time window
    st.subheader("Sensor streams and tier activity")
    n = len(stream)
    if stream.ignite_s is not None and st.checkbox("Zoom to ignition (±3 min)"):
        w0, w1 = max(0.0, (stream.ignite_s - 180) / 3600), (stream.ignite_s + 180) / 3600
    else:
        w0, w1 = st.slider("Time window (hours)", 0.0, 24.0, (0.0, 24.0), step=0.05)
    lo = max(0, int(w0 * 3600 / stream.dt))
    hi = min(n, max(lo + 2, int(w1 * 3600 / stream.dt)))

    temp = np.array(stream.temp)
    smoke = np.array(stream.smoke)
    t1 = Tier1(T)
    flag = np.array([t1.check(x) for x in stream.temp])
    cond = flag & (smoke >= S)
    hrs = np.arange(lo, hi) * stream.dt / 3600

    def in_win(t):
        return lo * stream.dt <= t < hi * stream.dt

    wake_t = [e["t"] for e in acts["event"]["events"] if in_win(e["t"])]

    fig, ax = plt.subplots(5, 1, figsize=(12, 9), sharex=True,
                           gridspec_kw={"height_ratios": [3, 3, 1, 1, 1.4]})
    ax[0].plot(hrs, temp[lo:hi], lw=0.7)
    ax[0].axhline(T, color="r", ls="--", lw=1)
    ax[0].set_ylabel("Temp (°C)")
    ax[1].plot(hrs, smoke[lo:hi], lw=0.7, color="tab:gray")
    ax[1].axhline(S, color="r", ls="--", lw=1)
    ax[1].set_ylabel("Smoke")
    ax[2].fill_between(hrs, 0, flag[lo:hi].astype(int), step="mid", color="tab:orange")
    ax[2].set_yticks([])
    ax[2].set_ylabel("Tier 1\nflag", rotation=0, labelpad=28, va="center")
    ax[3].fill_between(hrs, 0, cond[lo:hi].astype(int), step="mid", color="tab:purple", alpha=0.5)
    if wake_t:
        ax[3].vlines([t / 3600 for t in wake_t], 0, 1, colors="red", lw=1.5)
    ax[3].set_yticks([])
    ax[3].set_ylabel("Tier 2 / WAKE_UP\n(red = core wakes)", rotation=0, labelpad=48, va="center")
    for y, m in ((1, "polling_naive"), (0, "polling_validated")):
        for e in acts[m]["events"]:
            if e["tx"] and in_win(e["t"]):
                ax[4].scatter(e["t"] / 3600, y, marker="o" if e["fire"] else "x",
                              color="green" if e["fire"] else "red", s=28)
    ax[4].set_yticks([0, 1])
    ax[4].set_yticklabels(["polling\nvalidated", "polling\nnaive"], fontsize=8)
    ax[4].set_ylim(-0.6, 1.6)
    ax[4].set_xlabel("Hour of day   (polling row: green o = true alert, red x = false alert)")
    if stream.ignite_s is not None and in_win(stream.ignite_s):
        for a in ax:
            a.axvline(stream.ignite_s / 3600, color="k", ls=":", lw=1)
    ax[4].set_xlim(hrs[0], hrs[-1])
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    # ---- energy breakdown
    st.subheader("Energy breakdown per simulated day")
    parts = [("always_on_j", "Always-on floor"), ("wake_j", "Wake transitions"),
             ("cpu_j", "CPU execution"), ("sensing_j", "Sensor sampling"), ("radio_j", "Radio TX")]
    names = [LABELS[m] for m in WildfireSoC.MODES]
    fig2, ax2 = plt.subplots(figsize=(9, 3.4))
    left = np.zeros(3)
    for key, lab in parts:
        vals = np.array([summ[m][key] * 1e3 for m in WildfireSoC.MODES])
        ax2.barh(names, vals, left=left, label=lab)
        left += vals
    ax2.set_xlabel("Energy (mJ)")
    ax2.invert_yaxis()
    ax2.legend(fontsize=8)
    fig2.tight_layout()
    st.pyplot(fig2)
    plt.close(fig2)
    st.caption("Single seed. Your report's tables are means over several seeds, so expect small differences.")

# ================================================================== TAB 2
with tab2:
    st.subheader("Run firmware on the cycle-accurate pipeline")
    c1, c2, c3, c4 = st.columns(4)
    image = c1.selectbox("Firmware image", list(WildfireSoC.MODES))
    ftemp = c2.number_input("TEMP (°C)", 0, 255, 65)
    fsmoke = c3.number_input("SMOKE (0-100)", 0, 100, 45)
    ntrace = c4.slider("Trace cycles", 10, 250, 40, step=5)

    prog = soc.images[image]
    cpu, bus = run_fw(prog, int(ftemp), int(fsmoke), fwd, policy, trace=True)
    s = cpu.stats()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cycles", s["cycles"])
    m2.metric("Instructions retired", s["retired"])
    m3.metric("CPI", f"{s['cpi']:.2f}")
    m4.metric("Time at clock", f"{s['cycles'] / CONFIG['cpu']['clock_hz'] * 1e6:.0f} µs")
    st.write(f"**Radio packet:** {[hex(w) for _, w in bus.radio_log] or 'none (no alert)'}")
    st.write(f"Data stalls: {s['data_stalls']}, control penalty: {s['control_penalty']}, "
             f"forwards: {s['fwd_ex_mem']} + {s['fwd_mem_wb']}, "
             f"branches: {s['branches']} (mispredicted {s['mispredicts']})")
    fstart = st.number_input("Start at cycle", 1, max(1, s["cycles"]), 1, key="fw_start")
    st.markdown("**Pipeline diagram**")
    show_pipeline(cpu.format_trace(int(fstart) + ntrace - 1), forwarding=fwd, start=int(fstart))
    with st.expander("Raw text trace"):
        st.code(cpu.format_trace(ntrace), language=None)

    st.markdown("**Same firmware across all pipeline configurations**")
    rows = []
    for f_ in (True, False):
        for pol in PipelineCPU.POLICIES:
            c_, _ = run_fw(prog, int(ftemp), int(fsmoke), f_, pol)
            s_ = c_.stats()
            rows.append({"Forwarding": "on" if f_ else "off", "Branch policy": pol,
                         "Cycles": s_["cycles"], "Instructions": s_["retired"],
                         "CPI": round(s_["cpi"], 3), "Data stalls": s_["data_stalls"],
                         "Control penalty": s_["control_penalty"]})
    st.dataframe(rows, width="stretch")

    st.divider()
    st.subheader("Benchmark programs (pipeline vs golden model)")
    tests = sorted(glob.glob(os.path.join(ASM_DIR, "tests", "*.s")))
    if not tests:
        st.warning("No programs found in asm/tests/.")
    else:
        pick = st.selectbox("Program", tests, format_func=lambda p: os.path.basename(p))
        tprog = assemble_files([pick], TEST_DEFS)
        golden = GoldenCPU(Bus(tprog, 0, 0)).run()
        rows = []
        for f_ in (True, False):
            for pol in PipelineCPU.POLICIES:
                c_, _ = run_fw(tprog, 0, 0, f_, pol)
                s_ = c_.stats()
                rows.append({"Forwarding": "on" if f_ else "off", "Branch policy": pol,
                             "Cycles": s_["cycles"], "Instructions": s_["retired"],
                             "CPI": round(s_["cpi"], 3), "Data stalls": s_["data_stalls"],
                             "Control penalty": s_["control_penalty"],
                             "Matches golden": c_.regs == golden.regs})
        st.dataframe(rows, width="stretch")
        with st.expander("Pipeline diagram for this program (current sidebar settings)"):
            n2 = st.slider("Cycles to show", 10, 200, 30, key="bench_trace")
            c_, _ = run_fw(tprog, 0, 0, fwd, policy, trace=True)
            st.code(c_.format_trace(n2), language=None)

# ================================================================== TAB 3
with tab3:
    st.subheader("Files generated by `python main.py experiments`")
    res = os.path.join(ROOT, "results")
    pngs = sorted(glob.glob(os.path.join(res, "*.png")))
    csvs = sorted(glob.glob(os.path.join(res, "*.csv")))
    txts = sorted(glob.glob(os.path.join(res, "*.txt")))
    if not (pngs or csvs or txts):
        st.info("results/ is empty. Run `python main.py experiments` first.")
    for i in range(0, len(pngs), 2):
        cols = st.columns(2)
        for col, p in zip(cols, pngs[i:i + 2]):
            col.image(p, caption=os.path.basename(p), width="stretch")
    if csvs:
        import pandas as pd
        for p in csvs:
            with st.expander(os.path.basename(p)):
                st.dataframe(pd.read_csv(p), width="stretch")
    for p in txts:
        with st.expander(os.path.basename(p)):
            with open(p, encoding="utf-8", errors="replace") as fh:
                st.code(fh.read(), language=None)

# ================================================================== TAB 4
with tab4:
    show_stats(soc, cost_cfg, params)