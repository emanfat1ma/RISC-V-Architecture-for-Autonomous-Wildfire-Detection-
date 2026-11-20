"""Wildfire RISC-V SoC dashboard (redesigned). Run: streamlit run app.py"""
import glob
import os
import sys

import streamlit as st

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from config import CONFIG, make_config
from cpu_view import show_cpu
from mission_control import show_mission
from pipeline_view import show_pipeline
from results_tab import show_results
from sidebar_controls import controls
from sim.assembler import assemble_files
from sim.golden import GoldenCPU
from sim.memory import Bus
from sim.pipeline import PipelineCPU
from sim.sensors import generate
from sim.soc import ASM_DIR, WildfireSoC
from stats_tab import show_stats


@st.cache_resource(show_spinner="Assembling firmware...")
def get_soc(temp_c, smoke, persist, hold, poll_s, fwd, policy):
    return WildfireSoC(make_config(thresholds={"temp_c": temp_c, "smoke": smoke},
                                   tier2={"persistence": persist, "rearm_holdoff_s": hold},
                                   poll={"period_s": poll_s}, cpu={"forwarding": fwd, "branch_policy": policy}))


@st.cache_resource(show_spinner="Generating sensor data...")
def get_stream(scenario, seed):
    return generate(scenario, CONFIG["duration_s"], CONFIG["sample_period_s"], seed)


@st.cache_resource(show_spinner="Simulating all three designs (runs the real RISC-V core)...")
def get_activity(scenario, seed, *params):
    soc, stream = get_soc(*params), get_stream(scenario, seed)
    return {m: soc.simulate(m, stream) for m in WildfireSoC.MODES}


st.set_page_config(page_title="Wildfire node", layout="wide")
st.title("Event-driven wildfire node")
c = controls()
params = (c["T"], c["S"], c["persist"], c["hold"], c["poll_s"], c["fwd"], c["policy"])
soc, stream = get_soc(*params), get_stream(c["scenario"], c["seed"])
acts = get_activity(c["scenario"], c["seed"], *params)
cost_cfg = make_config(power=c["power"])
summ = {m: soc.summarize(acts[m], cost_cfg) for m in WildfireSoC.MODES}

tab1, tab2, tab3, tab4 = st.tabs(["Mission control", "RISC-V core", "Statistics & battery", "Saved results"])

with tab1:
    show_mission(stream, acts, summ, c["T"], c["S"], c["persist"], c["hold"], c["poll_s"])

with tab2:
    show_cpu(soc, c["fwd"], c["policy"])
    st.divider()
    st.subheader("Benchmark programs (pipeline vs golden model)")
    tests = sorted(glob.glob(os.path.join(ASM_DIR, "tests", "*.s")))
    if tests:
        pick = st.selectbox("Program", tests, format_func=os.path.basename)
        tprog = assemble_files([pick], {"TEMP_THRESH": 60, "SMOKE_THRESH": 30, "REQUIRE_SMOKE": 1})
        golden = GoldenCPU(Bus(tprog, 0, 0)).run()
        cpu = PipelineCPU(Bus(tprog, 0, 0), forwarding=c["fwd"], branch_policy=c["policy"], trace=True).run()
        st.write(f"{cpu.cycles} cycles, CPI {cpu.stats()['cpi']:.2f}. Matches the golden model: **{cpu.regs == golden.regs}**")
        b1, b2 = st.columns(2)
        n2 = b1.slider("Cycles to show", 10, 200, 30)
        start = int(b2.number_input("Start at cycle", 1, 5000, 1))
        show_pipeline(cpu.format_trace(start + n2 - 1), forwarding=c["fwd"], start=start)

with tab3:
    show_stats(soc, cost_cfg, params)

with tab4:
    show_results(ROOT)