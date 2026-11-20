"""
energy.py - Power / energy model (Step 9).

Energy is computed from an ACTIVITY summary (wake count, executed core cycles, ...)
produced by the SoC simulation, so the same simulation can be re-costed with other
parameters (sensitivity analysis) without re-running the processor model.

  E_total = E_always_on + E_wakeups + E_cpu + E_sensing + E_radio
    E_always_on : (event-driven) Tier1+Tier2+gated-leakage currents * Vdd * T
                  (polling)      CPU retention-sleep current * Vdd * T
    E_cpu       : P_active * (cycles executed on the simulated pipeline / f_clk)
    E_radio     : tx_count * (I_radio + I_doze) * Vdd * t_tx
"""
SECONDS_PER_YEAR = 365.25 * 24 * 3600


def compute_energy(act, cfg):
    p, V, T = cfg["power"], cfg["power"]["vdd"], act["duration_s"]
    f = cfg["cpu"]["clock_hz"]
    if act["mode"] == "event":
        always_on = (p["tier1_current_a"] + p["tier2_current_a"] + p["gated_core_leakage_a"]) * V * T
        wake = act["core_wakes"] * p["wake_transition_energy_j"]
    else:
        always_on = p["baseline_sleep_current_a"] * V * T
        wake = act["core_wakes"] * p["baseline_wake_energy_j"]
    cpu = p["active_current_a"] * V * act["core_cycles"] / f
    sensing = act["sensor_samples"] * p["sensor_sample_energy_j"]
    radio = act["tx_count"] * (p["radio_tx_current_a"] + p["doze_current_a"]) * V * p["radio_tx_time_s"]
    total = always_on + wake + cpu + sensing + radio
    return {"always_on_j": always_on, "wake_j": wake, "cpu_j": cpu, "sensing_j": sensing,
            "radio_j": radio, "total_j": total}


def battery_energy_j(cfg):
    return cfg["battery"]["capacity_mah"] / 1000.0 * cfg["power"]["vdd"] * 3600.0


def lifetime_years(avg_power_w, cfg, include_self_discharge=False):
    """Battery lifetime for a given average power draw."""
    cap = battery_energy_j(cfg)
    if include_self_discharge:
        avg_power_w += cap * cfg["battery"]["self_discharge_pct_per_year"] / 100.0 / SECONDS_PER_YEAR
    return cap / avg_power_w / SECONDS_PER_YEAR if avg_power_w > 0 else float("inf")
