"""stats_tab.py - many-run statistics and battery-life panel for the dashboard.

Usage in app.py (see the three edits in the chat):
    from stats_tab import show_stats
    ...
    with tab4:
        show_stats(soc, cost_cfg, params)
"""
import numpy as np

LABELS = {"event": "Event-driven",
          "polling_naive": "Polling (naive)",
          "polling_validated": "Polling (validated)"}
MODES = ("event", "polling_naive", "polling_validated")
SCENARIOS = ("normal", "heatwave", "wildfire")


def show_stats(soc, cost_cfg, params):
    import streamlit as st
    import matplotlib.pyplot as plt
    from config import CONFIG, make_config
    from sim.energy import SECONDS_PER_YEAR, battery_energy_j, lifetime_years
    from sim.sensors import generate
    from sim.soc import WildfireSoC

    st.subheader("Many-run statistics")
    st.caption("Runs every scenario with many random seeds, using the sidebar thresholds, persistence "
               "and polling period. One seed is one random day, so this shows what is typical, not lucky.")
    n_seeds = st.slider("Seeds per scenario", 3, 30, 10, key="stats_seeds")
    key = (n_seeds, *params)

    if st.button("Run statistics", key="stats_run"):
        batch = {sc: [] for sc in SCENARIOS}
        total, done = len(SCENARIOS) * n_seeds, 0
        bar = st.progress(0.0, text="Simulating...")
        for sc in SCENARIOS:
            for sd in range(1, n_seeds + 1):
                stream = generate(sc, CONFIG["duration_s"], CONFIG["sample_period_s"], sd)
                batch[sc].append({m: soc.simulate(m, stream) for m in WildfireSoC.MODES})
                done += 1
                bar.progress(done / total, text=f"{sc}, seed {sd} ({done}/{total})")
        bar.empty()
        st.session_state["stats_key"] = key
        st.session_state["stats_data"] = batch

    data = st.session_state.get("stats_data")
    if not data:
        st.info(f"Click **Run statistics** to simulate {len(SCENARIOS) * n_seeds} days "
                f"(roughly {len(SCENARIOS) * n_seeds * 0.5:.0f} seconds).")
        return
    if st.session_state.get("stats_key") != key:
        st.warning("Sidebar settings or the seed count changed since the last run. "
                   "Click **Run statistics** again to update.")

    # re-cost the saved activity with the current power assumptions (instant)
    res = {sc: [{m: soc.summarize(a[m], cost_cfg) for m in MODES} for a in data[sc]] for sc in data}
    N = len(res["wildfire"])

    st.markdown(f"**Did each design catch the fire? {N} wildfire days**")
    html = ""
    for m in MODES:
        rs = [r[m] for r in res["wildfire"]]
        lats = [r["latency_s"] for r in rs if r["latency_s"] is not None]
        dots = "".join('<span style="display:inline-block;width:13px;height:13px;border-radius:50%%;margin:2px;background:%s"></span>' % ("#ff6a3d" if r["missed_fire"] else "#6fbf8a") for r in rs)
        avg = f"{np.mean(lats):.0f} s to detect" if lats else "never detected"
        html += ('<div style="display:flex;gap:18px;align-items:center;margin:8px 0"><div style="width:210px"><b>%s</b><br><small>%s, %d missed</small></div><div>%s</div></div>'
                 % (LABELS[m], avg, sum(bool(r["missed_fire"]) for r in rs), dots))
    st.markdown(html + "<small>Each dot is one simulated wildfire day: green means the alert was sent, red means missed.</small>", unsafe_allow_html=True)
    st.markdown(f"**False alerts per day on heatwave days ({N} seeds)**")
    fa = {m: float(np.mean([r[m]["false_transmissions"] for r in res["heatwave"]])) for m in MODES}
    mxv, html = max(max(fa.values()), 0.5), ""
    for m in MODES:
        html += ('<div style="display:flex;gap:14px;align-items:center;margin:8px 0"><div style="width:210px"><b>%s</b></div><div style="flex:1"><div style="width:%.1f%%;min-width:4px;height:24px;border-radius:6px;background:%s"></div></div><div style="width:60px;text-align:right;font-size:18px;font-weight:700">%.1f</div></div>'
                 % (LABELS[m], fa[m] / mxv * 100, "#6fbf8a" if m == "event" else "#f2b84b", fa[m]))
    st.markdown(html, unsafe_allow_html=True)

    # ---------------- battery life
    st.divider()
    st.subheader("Battery life")
    b1, b2 = st.columns(2)
    cap = b1.number_input("Battery capacity (mAh)", 100, 20000, int(CONFIG["battery"]["capacity_mah"]),
                          step=100, key="bat_cap")
    sd_pct = b2.slider("Self-discharge (% of capacity lost per year)", 0.0, 10.0, 2.0, 0.25, key="bat_sd")
    bcfg = make_config(battery={"capacity_mah": cap, "self_discharge_pct_per_year": sd_pct})

    mix = CONFIG["mix"]
    avg_uw = {m: sum(mix[sc] * float(np.mean([r[m]["avg_power_uw"] for r in res[sc]])) for sc in mix)
              for m in MODES}
    st.caption("Average power is weighted by the deployment mix in config.py: "
               + ", ".join(f"{sc} {mix[sc] * 100:g}%" for sc in mix) + " of days.")

    leak_uw = battery_energy_j(bcfg) * sd_pct / 100.0 / SECONDS_PER_YEAR * 1e6
    mx, html = max(avg_uw.values()) + leak_uw, ""
    for m in MODES:
        yrs = lifetime_years(avg_uw[m] * 1e-6, bcfg, include_self_discharge=True)
        html += ('<div style="display:flex;gap:14px;align-items:center;margin:10px 0"><div style="width:170px"><b>%s</b></div><div style="flex:1;display:flex"><div style="width:%.2f%%;min-width:3px;background:#6fbf8a;height:26px"></div><div style="width:%.2f%%;background:#5a6f6b;height:26px"></div></div><div style="width:120px;text-align:right;font-size:20px;font-weight:700">%.0f years</div></div>'
                 % (LABELS[m], avg_uw[m] / mx * 100, leak_uw / mx * 100, yrs))
    st.markdown(html + "<small>Green: what the node draws. Grey: the battery leaking by itself. Ignoring the leak, the event-driven node would last %.0f years, which is not realistic.</small>" % lifetime_years(avg_uw["event"] * 1e-6, bcfg), unsafe_allow_html=True)

    if sd_pct > 0:
        leak_uw = battery_energy_j(bcfg) * sd_pct / 100.0 / SECONDS_PER_YEAR * 1e6
        st.info(f"At {sd_pct:g}%/yr the battery leaks about **{leak_uw:.1f} µW** all by itself, "
                f"versus {avg_uw['event']:.2f} µW drawn by the event-driven node. "
                f"That leak, not the node, decides the lifetime. The first column ignores it, "
                f"which is why it shows unrealistic numbers.")

    xs = np.linspace(0.25, 10, 40)
    fig, ax = plt.subplots(figsize=(8, 3.4))
    for m in MODES:
        ys = [lifetime_years(avg_uw[m] * 1e-6,
                             make_config(battery={"capacity_mah": cap, "self_discharge_pct_per_year": float(x)}),
                             include_self_discharge=True) for x in xs]
        ax.plot(xs, ys, label=LABELS[m])
    ax.axhline(10, color="r", ls="--", lw=1)
    ax.text(xs[-1], 10.6, "10-year target", color="r", ha="right", fontsize=8)
    ax.set_xlabel("Battery self-discharge (% per year)")
    ax.set_ylabel("Lifetime (years)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    st.caption("Higher self-discharge squeezes the three designs together: the battery's own leak "
               "dominates, so the power advantage matters less for lifetime than for energy.")