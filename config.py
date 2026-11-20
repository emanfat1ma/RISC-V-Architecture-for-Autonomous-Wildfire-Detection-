"""
config.py - ALL tunable parameters live here (Step 9: "one config file").

IMPORTANT: every number in 'power' and 'battery' is a modelling ASSUMPTION, not a
measurement. Replace them with datasheet values you can cite (e.g. a low-power MCU
and a LoRa-class radio) and state them in your report. The sensitivity experiment
shows how much the conclusions depend on each one.
"""
import copy

CONFIG = {
    "seed": 1,
    "duration_s": 24 * 3600,        # simulated time per scenario (one day)
    "sample_period_s": 1.0,         # sensor/Tier-1 sampling period of the simulation

    # ---- detection thresholds (shared by Tier 1/2 hardware and the polling firmware)
    "thresholds": {"temp_c": 60, "smoke": 30},

    # ---- Tier 2 validation logic
    "tier2": {"persistence": 5,         # consecutive samples that must satisfy temp AND smoke
              "rearm_holdoff_s": 300},  # after an alert, stay quiet this long (no alert spam)

    # ---- conventional baseline node
    "poll": {"period_s": 60},

    # ---- RISC-V core
    "cpu": {"clock_hz": 1_000_000, "forwarding": True, "branch_policy": "not_taken"},

    # ---- power model (ASSUMPTIONS - cite datasheets in the report)
    "power": {
        "vdd": 3.0,                          # V
        "tier1_current_a": 18e-9,            # always-on analog comparator (design target from proposal)
        "tier2_current_a": 60e-9,            # always-on validation logic (assumption)
        "gated_core_leakage_a": 5e-9,        # leakage of the power-gated core (assumption)
        "baseline_sleep_current_a": 1.0e-6,  # CPU retention sleep + RTC of a conventional node
        "active_current_a": 300e-6,          # core current while executing (at clock_hz)
        "doze_current_a": 20e-6,             # core idle while radio transmits
        "wake_transition_energy_j": 2e-6,    # power-gate wake-up (rail ramp, reset) per event
        "baseline_wake_energy_j": 0.3e-6,    # timer wake-up of the conventional node
        "sensor_sample_energy_j": 30e-6,     # ADC + settling energy per sensor sampling
        "radio_tx_current_a": 50e-3,         # radio transmit current
        "radio_tx_time_s": 0.2,              # air time of one alert packet
    },

    # ---- battery
    "battery": {"capacity_mah": 3000,
                "self_discharge_pct_per_year": 0.0},   # proposal excludes self-discharge

    # ---- deployment mix used to turn per-day energy into an annual estimate
    "mix": {"normal": 0.92, "heatwave": 0.075, "wildfire": 0.005},
}


def make_config(**overrides):
    """Deep copy of CONFIG with nested overrides, e.g. make_config(tier2={'persistence': 3})."""
    cfg = copy.deepcopy(CONFIG)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg
