"""sidebar_controls.py - the redesigned controls panel. Returns every setting app.py needs."""
import streamlit as st

from config import CONFIG
from sim.pipeline import PipelineCPU

PRESETS = {"Sensitive": (50, 20, 3), "Balanced": (60, 30, 5), "Strict": (70, 50, 8)}


def controls():
    P0 = CONFIG["power"]
    with st.sidebar:
        st.subheader("Set up the day")
        scenario = st.segmented_control("Scenario", ["normal", "heatwave", "wildfire"], default="wildfire",
                                        format_func=str.capitalize) or "wildfire"
        preset = st.segmented_control("Sensitivity", list(PRESETS), default="Balanced") or "Balanced"
        T0, S0, N0 = PRESETS[preset]
        st.caption(f"{preset}: over {T0} °C and smoke over {S0}, for {N0} seconds in a row.")
        poll_s = st.segmented_control("Compare with polling every (s)", [10, 30, 60, 120, 300], default=60) or 60

        with st.expander("Advanced settings"):
            T = st.slider("Temperature limit (°C)", 30, 100, T0, key=f"T_{preset}")
            S = st.slider("Smoke limit", 5, 80, S0, key=f"S_{preset}")
            persist = st.slider("Persistence (samples)", 1, 20, N0, key=f"N_{preset}")
            hold = st.slider("Re-arm hold-off (s)", 0, 900, CONFIG["tier2"]["rearm_holdoff_s"], step=30)
            seed = int(st.number_input("Random seed", 0, 9999, CONFIG["seed"]))
            fwd = st.checkbox("Forwarding", CONFIG["cpu"]["forwarding"])
            policy = st.selectbox("Branch policy", list(PipelineCPU.POLICIES),
                                  index=list(PipelineCPU.POLICIES).index(CONFIG["cpu"]["branch_policy"]))

        with st.expander("Power assumptions (all need a datasheet source)"):
            st.caption("Amber means an assumption. Replace each with a cited value and note the source in the report.")
            power = {
                "baseline_sleep_current_a": st.number_input("Baseline sleep current (µA)", 0.0, 50.0, P0["baseline_sleep_current_a"] * 1e6, 0.1) * 1e-6,
                "tier1_current_a": st.number_input("Tier 1 current (nA)", 0.0, 1000.0, P0["tier1_current_a"] * 1e9, 1.0) * 1e-9,
                "tier2_current_a": st.number_input("Tier 2 current (nA)", 0.0, 1000.0, P0["tier2_current_a"] * 1e9, 1.0) * 1e-9,
                "gated_core_leakage_a": st.number_input("Gated-core leakage (nA)", 0.0, 1000.0, P0["gated_core_leakage_a"] * 1e9, 1.0) * 1e-9,
                "sensor_sample_energy_j": st.number_input("Sensor sample energy (µJ)", 0.0, 500.0, P0["sensor_sample_energy_j"] * 1e6, 1.0) * 1e-6,
                "radio_tx_current_a": st.number_input("Radio TX current (mA)", 0.0, 500.0, P0["radio_tx_current_a"] * 1e3, 1.0) * 1e-3,
                "radio_tx_time_s": st.number_input("Radio air time (s)", 0.0, 5.0, P0["radio_tx_time_s"], 0.05),
            }
    return {"scenario": scenario, "seed": seed, "T": T, "S": S, "persist": persist, "hold": hold,
            "poll_s": poll_s, "fwd": fwd, "policy": policy, "power": power}