"""
experiments.py - Step 10/11: all experiments, CSV tables and plots for the report.

    python main.py experiments            # everything (about a minute)
    python main.py experiments --quick    # 2 seeds, fewer sweep points

Outputs go to results/ :
    verification.csv        every verification check (pipeline == golden model)
    pipeline_cpi.csv/.png   CPI, stalls, flushes, forwards per program and pipeline config
    cold_start.csv          cycles/time from WAKE_UP until the handler runs / radio starts
    trace_*.txt             cycle-by-cycle pipeline diagrams (stall / forwarding examples)
    scenario_runs.csv       one row per (scenario, mode, seed)
    scenario_summary.csv/.png  mean over seeds: energy, wake-ups, false alarms, latency
    lifetime.csv            deployment-mix average power and battery-life estimate
    sweeps.csv/.png         persistence / smoke-threshold / temperature-threshold sweeps
    poll_period_sweep.csv   polling baseline: energy vs detection latency trade-off
    sensitivity.csv/.png    +-factor-of-2 change of every power parameter
"""
import csv
import glob
import os
import statistics as stats

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config import make_config
from sim.assembler import assemble_files
from sim.energy import battery_energy_j, compute_energy, lifetime_years
from sim.memory import Bus
from sim.pipeline import PipelineCPU
from sim.sensors import generate
from sim.soc import WildfireSoC, ASM_DIR
from tests.run_tests import CONFIGS, DEFINES, run_all

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "results")
MODES = WildfireSoC.MODES
SCENARIOS = ("normal", "heatwave", "wildfire")
LABEL = {"event": "Event-driven", "polling_naive": "Polling (naive)",
         "polling_validated": "Polling (validated)"}


def write_csv(name, rows, fieldnames=None):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    if not rows:
        return path
    fieldnames = fieldnames or list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in r.items()})
    return path


def cfg_name(fw, pol):
    return f"fwd={'on' if fw else 'off'}/{pol}"


def mean(xs):
    xs = [x for x in xs if x is not None]
    return stats.fmean(xs) if xs else None


# ====================================================================== 1. verification
def exp_verification():
    results, ok = run_all(verbose=False)
    write_csv("verification.csv", results)
    n = sum(r["passed"] for r in results)
    print(f"[verification] {n}/{len(results)} checks passed -> results/verification.csv")
    return ok


# ====================================================================== 2. pipeline CPI
def _benchmarks():
    progs = {}
    for p in sorted(glob.glob(os.path.join(ASM_DIR, "tests", "*.s"))):
        name = os.path.splitext(os.path.basename(p))[0]
        if name == "arith":
            continue
        progs[name] = (assemble_files([p]), 0, 0)
    fw = assemble_files([f"{ASM_DIR}/common.s", f"{ASM_DIR}/boot.s", f"{ASM_DIR}/handler.s"], DEFINES)
    progs["wake_handler"] = (fw, 65, 45)
    return progs


def exp_pipeline_cpi():
    rows = []
    for name, (prog, t, s) in _benchmarks().items():
        for fw, pol in CONFIGS:
            cpu = PipelineCPU(Bus(prog, t, s), forwarding=fw, branch_policy=pol).run()
            rows.append({"program": name, "forwarding": fw, "branch_policy": pol, **cpu.stats()})
    write_csv("pipeline_cpi.csv", rows)

    progs = list(dict.fromkeys(r["program"] for r in rows))
    def cpi(prog, fw, pol):
        return next(r["cpi"] for r in rows if r["program"] == prog and r["forwarding"] == fw
                    and r["branch_policy"] == pol)

    fig, axs = plt.subplots(1, 2, figsize=(13, 4.2))
    w = 0.38
    xs = range(len(progs))
    axs[0].bar([x - w / 2 for x in xs], [cpi(p, True, "not_taken") for p in progs], w, label="forwarding ON")
    axs[0].bar([x + w / 2 for x in xs], [cpi(p, False, "not_taken") for p in progs], w, label="forwarding OFF")
    axs[0].set_title("Effect of data forwarding (branch policy: not-taken)")
    pols = PipelineCPU.POLICIES
    w3 = 0.27
    for k, pol in enumerate(pols):
        axs[1].bar([x + (k - 1) * w3 for x in xs], [cpi(p, True, pol) for p in progs], w3, label=pol)
    axs[1].set_title("Effect of branch handling policy (forwarding ON)")
    for ax in axs:
        ax.set_xticks(list(xs)); ax.set_xticklabels(progs, rotation=30, ha="right")
        ax.set_ylabel("CPI"); ax.axhline(1, color="gray", lw=0.8, ls="--"); ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "pipeline_cpi.png"), dpi=150); plt.close(fig)
    print("[pipeline] CPI table -> results/pipeline_cpi.csv, pipeline_cpi.png")
    print(f"   {'program':<14}" + "".join(f"{cfg_name(f, p):>22}" for f, p in CONFIGS))
    for p in progs:
        print(f"   {p:<14}" + "".join(f"{cpi(p, f, pol):>22.3f}" for f, pol in CONFIGS))


# ====================================================================== 3. traces + cold start
def exp_traces_and_cold_start():
    # pipeline diagrams for the report
    cases = [("loaduse", True, "not_taken", 28, "trace_loaduse_forwarding.txt"),
             ("raw_chain", True, "not_taken", 16, "trace_raw_chain_forwarding_on.txt"),
             ("raw_chain", False, "not_taken", 24, "trace_raw_chain_forwarding_off.txt"),
             ("branches", True, "bimodal", 40, "trace_branches_bimodal.txt")]
    for prog, fw, pol, rows, fname in cases:
        p = assemble_files([os.path.join(ASM_DIR, "tests", prog + ".s")])
        cpu = PipelineCPU(Bus(p), forwarding=fw, branch_policy=pol, trace=True).run()
        with open(os.path.join(OUT, fname), "w") as f:
            f.write(f"# {prog}.s  forwarding={'on' if fw else 'off'}  branch_policy={pol}\n")
            f.write("# 'x' = squashed (wrong-path) instruction, '(stall)' = held by hazard unit\n")
            f.write(cpu.format_trace(rows) + "\n")
    # cold-start cost of the power-gated core
    rows = []
    cfg = make_config()
    for fw, pol in CONFIGS:
        cfg["cpu"].update(forwarding=fw, branch_policy=pol)
        soc = WildfireSoC(cfg)
        r = soc.run_core("event", 65, 45)
        f = cfg["cpu"]["clock_hz"]
        # first handler instruction retires 5 cycles after it is fetched -> boot ROM = handler_start - 5
        rows.append({"config": cfg_name(fw, pol), "boot_cycles": r["handler_start_cycle"] - 5,
                     "cycles_to_first_radio_write": r["first_radio_cycle"], "total_cycles": r["cycles"],
                     "instructions": r["retired"], "cpi": r["stats"]["cpi"],
                     "wake_to_radio_us": r["first_radio_cycle"] / f * 1e6,
                     "total_active_us": r["cycles"] / f * 1e6})
    write_csv("cold_start.csv", rows)
    print("[cold start] results/cold_start.csv + trace_*.txt written")
    dflt = make_config()["cpu"]
    base = next(r for r in rows if r["config"] == cfg_name(dflt["forwarding"], dflt["branch_policy"]))
    print(f"   default config ({base['config']}): boot={base['boot_cycles']} cycles, WAKE_UP->radio write = "
          f"{base['cycles_to_first_radio_write']} cycles ({base['wake_to_radio_us']:.0f} us @ 1 MHz)")


# ====================================================================== 4. scenarios
def get_streams(cfg, seeds):
    return {(sc, sd): generate(sc, cfg["duration_s"], cfg["sample_period_s"], sd)
            for sc in SCENARIOS for sd in seeds}


def run_scenarios(cfg, streams, seeds):
    soc = WildfireSoC(cfg)
    acts = {}
    for (sc, sd), st in streams.items():
        for m in MODES:
            acts[(sc, m, sd)] = soc.simulate(m, st)
    return soc, acts


def exp_scenarios(seeds):
    cfg = make_config()
    streams = get_streams(cfg, seeds)
    soc, acts = run_scenarios(cfg, streams, seeds)

    runs, summary = [], []
    for sc in SCENARIOS:
        for m in MODES:
            rs = [soc.summarize(acts[(sc, m, sd)]) | {"seed": sd} for sd in seeds]
            runs += rs
            lat = [r["latency_s"] for r in rs if r["latency_s"] is not None]
            summary.append({
                "scenario": sc, "mode": m,
                "energy_mj_per_day": mean([r["energy_j"] for r in rs]) * 1e3,
                "avg_power_uw": mean([r["avg_power_uw"] for r in rs]),
                "core_wakeups": mean([r["core_wakeups"] for r in rs]),
                "idle_wakeups": mean([r["idle_wakeups"] for r in rs]),
                "transmissions": mean([r["transmissions"] for r in rs]),
                "false_transmissions": mean([r["false_transmissions"] for r in rs]),
                "missed_fires": sum(1 for r in rs if r["missed_fire"]) if sc == "wildfire" else "",
                "latency_mean_s": mean(lat) if lat else "",
                "latency_max_s": max(lat) if lat else "",
                "avg_cycles_per_wake": mean([r["avg_cycles_per_wake"] for r in rs]),
            })
    write_csv("scenario_runs.csv", runs, ["scenario", "mode", "seed", "energy_j", "avg_power_uw",
              "core_wakeups", "idle_wakeups", "transmissions", "false_transmissions", "missed_fire",
              "latency_s", "core_cycles", "always_on_j", "wake_j", "cpu_j", "sensing_j", "radio_j"])
    write_csv("scenario_summary.csv", summary)

    fig, axs = plt.subplots(1, 3, figsize=(14, 4))
    for ax, key, title in zip(axs, ("energy_mj_per_day", "core_wakeups", "false_transmissions"),
                              ("Energy per simulated day (mJ, log)", "CPU wake-ups per day (log)",
                               "False alarm transmissions per day")):
        w = 0.27
        for k, m in enumerate(MODES):
            vals = [next(r[key] for r in summary if r["scenario"] == sc and r["mode"] == m) for sc in SCENARIOS]
            ax.bar([i + (k - 1) * w for i in range(3)], [max(v, 1e-3) if key != "false_transmissions" else v for v in vals],
                   w, label=LABEL[m])
        ax.set_xticks(range(3)); ax.set_xticklabels(SCENARIOS); ax.set_title(title)
        if key != "false_transmissions":
            ax.set_yscale("log")
        ax.legend(fontsize=8, loc="best")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "scenario_summary.png"), dpi=150); plt.close(fig)

    print(f"[scenarios] mean over seeds {list(seeds)}  -> results/scenario_summary.csv, scenario_summary.png")
    print(f"   {'scenario':<9}{'mode':<20}{'mJ/day':>9}{'uW':>8}{'wakes':>7}{'idle':>7}{'falseTX':>8}{'lat(s)':>9}")
    for r in summary:
        lat = f"{r['latency_mean_s']:.1f}" if r["latency_mean_s"] != "" else "-"
        print(f"   {r['scenario']:<9}{LABEL[r['mode']]:<20}{r['energy_mj_per_day']:>9.2f}{r['avg_power_uw']:>8.2f}"
              f"{r['core_wakeups']:>7.0f}{r['idle_wakeups']:>7.0f}{r['false_transmissions']:>8.1f}{lat:>9}")
    return cfg, soc, acts, summary


# ====================================================================== 5. lifetime
def mix_power(acts, cfg, seeds, mode):
    """Deployment-mix weighted average power (W) from per-scenario daily activities."""
    total = 0.0
    for sc, wgt in cfg["mix"].items():
        e = mean([compute_energy(acts[(sc, mode, sd)], cfg)["total_j"] for sd in seeds])
        total += wgt * e
    return total / (cfg["duration_s"])


def exp_lifetime(cfg, acts, seeds):
    rows = []
    cap = battery_energy_j(cfg)
    cfg_sd = make_config(battery={"self_discharge_pct_per_year": 2.0}, power=cfg["power"])
    base = {}
    for m in MODES:
        P = mix_power(acts, cfg, seeds, m)
        base[m] = P
    for m in MODES:
        P = base[m]
        rows.append({"mode": m, "avg_power_uw": P * 1e6,
                     "lifetime_years_no_selfdischarge": lifetime_years(P, cfg),
                     "lifetime_years_2pct_selfdischarge": lifetime_years(P, cfg_sd, True),
                     "power_ratio_vs_event": P / base["event"], "battery_energy_j": cap})
    write_csv("lifetime.csv", rows)
    print(f"[lifetime] deployment mix {cfg['mix']}, battery {cfg['battery']['capacity_mah']} mAh -> results/lifetime.csv")
    for r in rows:
        print(f"   {LABEL[r['mode']]:<20} P={r['avg_power_uw']:7.3f} uW  life={r['lifetime_years_no_selfdischarge']:10.1f} y "
              f"(2%/yr self-discharge: {r['lifetime_years_2pct_selfdischarge']:6.1f} y)  x{r['power_ratio_vs_event']:.1f} vs event-driven")


# ====================================================================== 6. sweeps
def exp_sweeps(seeds, quick=False):
    base = make_config()
    streams = get_streams(base, seeds)
    sweeps = {
        "persistence": ("tier2", "persistence", [1, 2, 3, 5, 8, 12] if quick else [1, 2, 3, 5, 8, 12, 20]),
        "smoke_threshold": ("thresholds", "smoke", [15, 25, 30, 40, 60] if quick else [10, 15, 20, 25, 30, 40, 50, 60]),
        "temp_threshold": ("thresholds", "temp_c", [50, 60, 70, 90] if quick else [45, 50, 55, 60, 65, 70, 80, 100]),
    }
    rows = []
    for name, (grp, key, values) in sweeps.items():
        for v in values:
            cfg = make_config(**{grp: {key: v}})
            soc = WildfireSoC(cfg)
            hw = [soc.summarize(soc.simulate("event", streams[("heatwave", sd)])) for sd in seeds]
            wf = [soc.summarize(soc.simulate("event", streams[("wildfire", sd)])) for sd in seeds]
            nm = [soc.summarize(soc.simulate("event", streams[("normal", sd)])) for sd in seeds]
            lat = [r["latency_s"] for r in wf if r["latency_s"] is not None]
            rows.append({"sweep": name, "value": v,
                         "false_wakes_heatwave": mean([r["idle_wakeups"] for r in hw]),
                         "false_wakes_normal": mean([r["idle_wakeups"] for r in nm]),
                         "missed_fires": sum(1 for r in wf if r["missed_fire"]),
                         "latency_mean_s": mean(lat) if lat else "",
                         "energy_mj_heatwave": mean([r["energy_j"] for r in hw]) * 1e3})
    write_csv("sweeps.csv", rows)

    fig, axs = plt.subplots(2, 3, figsize=(14, 6.5))
    for col, name in enumerate(sweeps):
        rs = [r for r in rows if r["sweep"] == name]
        xs = [r["value"] for r in rs]
        axs[0, col].plot(xs, [r["false_wakes_heatwave"] for r in rs], "o-", label="heatwave")
        axs[0, col].plot(xs, [r["false_wakes_normal"] for r in rs], "s--", label="normal")
        axs[0, col].set_title(f"False wake-ups/day vs {name}"); axs[0, col].legend()
        lat = [(x, r["latency_mean_s"]) for x, r in zip(xs, rs) if r["latency_mean_s"] != ""]
        if lat:
            axs[1, col].plot(*zip(*lat), "o-", color="tab:red")
        miss = [x for x, r in zip(xs, rs) if r["missed_fires"]]
        axs[1, col].set_title(f"Detection latency (s) vs {name}")
        axs[1, col].set_xlabel(name + (f"   (missed fires at {miss})" if miss else ""))
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "sweeps.png"), dpi=150); plt.close(fig)
    print("[sweeps] results/sweeps.csv, sweeps.png")
    for name in sweeps:
        print(f"   {name}:")
        for r in [r for r in rows if r["sweep"] == name]:
            lat = f"{r['latency_mean_s']:.1f}" if r["latency_mean_s"] != "" else "-"
            print(f"      {r['value']:>5}: false wakes (heatwave) {r['false_wakes_heatwave']:5.1f}  "
                  f"latency {lat:>6} s  missed {r['missed_fires']}")

    # polling period trade-off
    # latency of polling depends on where ignition falls between two polls -> use many seeds
    many = list(range(1, 11 if quick else 31))
    wf_streams = {sd: generate("wildfire", base["duration_s"], base["sample_period_s"], sd) for sd in many}
    prow = []
    for period in ([10, 60, 300] if quick else [10, 30, 60, 120, 300]):
        cfg = make_config(poll={"period_s": period})
        soc = WildfireSoC(cfg)
        nm = [soc.summarize(soc.simulate("polling_validated", streams[("normal", sd)])) for sd in seeds]
        wf = [soc.summarize(soc.simulate("polling_validated", wf_streams[sd])) for sd in many]
        lat = [r["latency_s"] for r in wf if r["latency_s"] is not None]
        prow.append({"poll_period_s": period, "avg_power_uw_normal_day": mean([r["avg_power_uw"] for r in nm]),
                     "latency_mean_s": mean(lat) if lat else "", "latency_max_s": max(lat) if lat else "",
                     "missed_fires": sum(1 for r in wf if r["missed_fire"]), "wildfire_runs": len(many)})
    write_csv("poll_period_sweep.csv", prow)
    print("[poll period] results/poll_period_sweep.csv")
    for r in prow:
        lm = f"{r['latency_mean_s']:.1f}" if r["latency_mean_s"] != "" else "-"
        print(f"   every {r['poll_period_s']:>4} s: {r['avg_power_uw_normal_day']:.2f} uW (normal day), mean latency {lm} s")


# ====================================================================== 7. sensitivity
def exp_sensitivity(cfg, acts, seeds):
    params = ["tier1_current_a", "tier2_current_a", "gated_core_leakage_a", "baseline_sleep_current_a",
              "active_current_a", "doze_current_a", "wake_transition_energy_j", "baseline_wake_energy_j",
              "sensor_sample_energy_j", "radio_tx_current_a", "radio_tx_time_s"]

    def ratio(c):
        return mix_power(acts, c, seeds, "polling_validated") / mix_power(acts, c, seeds, "event")

    def ratio_normal(c):
        e = mean([compute_energy(acts[("normal", "event", sd)], c)["total_j"] for sd in seeds])
        p = mean([compute_energy(acts[("normal", "polling_validated", sd)], c)["total_j"] for sd in seeds])
        return p / e

    nominal, nominal_n = ratio(cfg), ratio_normal(cfg)
    rows = []
    for k in params:
        row = {"parameter": k, "nominal_ratio_mix": nominal, "nominal_ratio_normal_day": nominal_n}
        for f in (0.5, 2.0):
            c = make_config(power={k: cfg["power"][k] * f})
            row[f"ratio_mix_x{f}"] = ratio(c)
            row[f"ratio_normal_x{f}"] = ratio_normal(c)
        rows.append(row)
    write_csv("sensitivity.csv", rows)

    rows_s = sorted(rows, key=lambda r: abs(r["ratio_normal_x2.0"] - r["ratio_normal_x0.5"]))
    fig, ax = plt.subplots(figsize=(8, 5))
    for i, r in enumerate(rows_s):
        ax.barh(i, r["ratio_normal_x2.0"] - nominal_n, left=nominal_n, color="tab:red", alpha=0.7)
        ax.barh(i, r["ratio_normal_x0.5"] - nominal_n, left=nominal_n, color="tab:blue", alpha=0.7)
    ax.axvline(nominal_n, color="k", lw=1)
    ax.set_yticks(range(len(rows_s))); ax.set_yticklabels([r["parameter"] for r in rows_s], fontsize=8)
    ax.set_xlabel("energy ratio polling(validated) / event-driven, normal day")
    ax.set_title("Sensitivity: red = parameter x2, blue = parameter x0.5")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "sensitivity.png"), dpi=150); plt.close(fig)
    print(f"[sensitivity] nominal energy ratio polling/event: normal day {nominal_n:.1f}x, deployment mix {nominal:.1f}x")
    for r in sorted(rows, key=lambda r: -abs(r["ratio_normal_x2.0"] - r["ratio_normal_x0.5"])):
        print(f"   {r['parameter']:<28} x0.5 -> {r['ratio_normal_x0.5']:7.1f}x    x2 -> {r['ratio_normal_x2.0']:7.1f}x")


# ====================================================================== driver
def run_all_experiments(quick=False):
    os.makedirs(OUT, exist_ok=True)
    seeds = [1, 2] if quick else [1, 2, 3, 4, 5]
    ok = exp_verification()
    exp_pipeline_cpi()
    exp_traces_and_cold_start()
    cfg, soc, acts, _ = exp_scenarios(seeds)
    exp_lifetime(cfg, acts, seeds)
    exp_sweeps(seeds[:3], quick)
    exp_sensitivity(cfg, acts, seeds)
    print(f"\nDone. Everything is in {OUT}")
    return ok
