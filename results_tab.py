"""results_tab.py - "Results for your report": a curated list on the left, one result at a time on the right.

Only the items in ITEMS are shown by default. Any other file in results/ is tucked into "Other files".
Takeaways are taken from the project report (Section 8); captions are suggestions to edit.
"""
import datetime
import glob
import os
import subprocess
import sys

import pandas as pd
import streamlit as st

ITEMS = [
    {"tag": "Report 8.1", "title": "Pipeline speed (CPI)", "head": "How fast the CPU runs the code",
     "what": "Clock ticks per instruction (CPI) for each forwarding and branch setting. Lower is better.",
     "take": "Forwarding is the biggest lever: a dependent chain drops from CPI 3.0 to 1.4.",
     "png": "pipeline_cpi", "csv": "pipeline_cpi", "cap": "Figure 8.1. CPI of eight programs under six pipeline settings."},
    {"tag": "Report 8.2", "title": "Cost of waking up", "head": "What one wake-up costs the CPU",
     "what": "The cold-boot cost of power gating for each pipeline setting.",
     "take": "Power gating wipes the CPU, so every wake starts from boot: about 100 cycles with the default settings.",
     "png": None, "csv": "cold_start", "cap": "Table 8.2. Cold-start cost of power gating."},
    {"tag": "Report 8.3", "title": "Energy per day", "head": "Energy per day: event-driven against polling",
     "what": "Energy, CPU wake-ups and false alerts for the three designs on normal, heatwave and wildfire days (log scales).",
     "take": "On a normal day the event-driven node uses about 14 times less energy and never wakes the CPU.",
     "png": "scenario_summary", "csv": "scenario_summary", "cap": "Figure 8.3. Daily energy, wake-ups and false alerts by scenario."},
    {"tag": "Report 8.4", "title": "Battery life", "head": "How long the battery lasts",
     "what": "Battery life for each design, with and without battery self-discharge.",
     "take": "Without self-discharge the lifetimes are not physically meaningful. With 2% a year, both designs pass 10 years (about 49 against 42).",
     "png": None, "csv": "lifetime", "cap": "Table 8.4. Estimated battery life."},
    {"tag": "Report 8.5", "title": "False wake-ups and speed", "head": "Trading false wake-ups against detection time",
     "what": "How persistence and the temperature and smoke limits change false wake-ups and detection delay.",
     "take": "Persistence 1 causes false wakes on heatwave days. From 2 samples up they vanish, at the cost of slower detection (9 s at 1 sample, 28 s at 20).",
     "png": "sweeps", "csv": "sweeps", "cap": "Figure 8.5. False wake-ups and detection latency against persistence and thresholds."},
    {"tag": "Report 8.5", "title": "Polling period trade-off", "head": "Polling faster costs energy",
     "what": "Normal-day power and detection delay for different polling periods.",
     "take": "Even polling every 10 s (14.0 s delay) is slower than event-driven (13 s), while using about 24 times the power.",
     "png": None, "csv": "poll_period_sweep", "cap": "Table 8.5. Polling period against power and detection delay."},
    {"tag": "Report 8.6", "title": "Power sensitivity", "head": "Which assumption matters most",
     "what": "How the normal-day energy ratio changes when each power number is halved or doubled.",
     "take": "The result rests mainly on the always-on floor and on sensor sampling, not on the CPU's energy.",
     "png": "sensitivity", "csv": "sensitivity", "cap": "Figure 8.6. Sensitivity of the energy ratio to each power assumption."},
    {"tag": "Check", "title": "Correctness checks", "head": "Is the simulator correct?",
     "what": "Every automated check: assembler, golden model, pipeline against golden model, and firmware.",
     "take": None, "png": None, "csv": "verification", "cap": ""},
    {"tag": "Logs", "title": "Pipeline step logs", "head": "Pipeline diagrams as text",
     "what": "Cycle-by-cycle logs of four example programs, showing stalls and flushes.",
     "take": None, "png": None, "csv": None, "cap": ""},
]
PASS_WORDS = {"true", "pass", "passed", "ok", "1", "yes", "success"}


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def _nice(df):
    df = df.copy()
    df.columns = [str(c).replace("_", " ").capitalize() for c in df.columns]
    return df


def _passed(df):
    col = next((c for c in df.columns if str(c).strip().lower() in ("passed", "pass", "ok", "result", "status", "success")), None)
    return None if col is None else int(df[col].astype(str).str.strip().str.lower().isin(PASS_WORDS).sum())


def show_results(root):
    res = os.path.join(root, "results")
    files = glob.glob(os.path.join(res, "*"))

    # ---------------- header
    h1, h2 = st.columns([3, 2], vertical_alignment="center")
    h1.subheader("Results for your report")
    h1.caption("Pick a result on the left. Each one says what it shows and where it goes in the report.")
    with h2:
        ver = os.path.join(res, "verification.csv")
        if os.path.exists(ver):
            df = pd.read_csv(ver)
            ok = _passed(df)
            st.markdown(f"**{ok} of {len(df)} checks passed**" if ok is not None else f"**{len(df)} checks listed**")
        if files:
            st.caption("Generated " + datetime.datetime.fromtimestamp(max(os.path.getmtime(f) for f in files)).strftime("%d %b %Y, %I:%M %p"))
        with st.popover("Refresh results"):
            st.write("This reruns every experiment and overwrites the files in results/. It can take a few minutes.")
            quick = st.checkbox("Quick mode (fewer seeds)", value=True)
            if st.button("Yes, refresh now"):
                with st.spinner("Running the experiments..."):
                    p = subprocess.run([sys.executable, "main.py", "experiments"] + (["--quick"] if quick else []),
                                       cwd=root, capture_output=True, text=True)
                if p.returncode == 0:
                    st.success("Finished. Reload the page to see the new results.")
                else:
                    st.error("The experiments failed.")
                    st.code((p.stdout[-1000:] + p.stderr[-1000:]) or "(no output)", language=None)

    left, right = st.columns([1, 2.4])
    with left:
        i = st.radio("Report sections", range(len(ITEMS)), label_visibility="collapsed",
                     format_func=lambda k: f"{ITEMS[k]['tag']}  -  {ITEMS[k]['title']}")
        st.caption("Nothing here changes unless you press Refresh results.")
        shown = {x["png"] for x in ITEMS if x["png"]} | {x["csv"] for x in ITEMS if x["csv"]}
        extra = [f for f in sorted(files) if os.path.splitext(os.path.basename(f))[0] not in shown
                 and not os.path.basename(f).startswith("trace_")]
        if extra:
            with st.expander("Other files"):
                for f in extra:
                    st.download_button(os.path.basename(f), _read(f), os.path.basename(f), key=f"x_{os.path.basename(f)}")

    it = ITEMS[i]
    with right, st.container(border=True):
        st.caption(it["tag"])
        st.header(it["head"])
        st.write(it["what"])
        if it["take"]:
            st.success("**Takeaway:** " + it["take"])
        png = os.path.join(res, (it["png"] or "") + ".png") if it["png"] else None
        csv = os.path.join(res, (it["csv"] or "") + ".csv") if it["csv"] else None
        if png:
            if os.path.exists(png):
                st.image(png, width="stretch")
            else:
                st.info("This figure has not been generated yet. Use Refresh results.")
        if it["tag"] == "Logs":
            traces = sorted(glob.glob(os.path.join(res, "trace_*.txt")))
            if traces:
                pick = st.selectbox("Example program", traces, format_func=lambda p: os.path.basename(p)[6:-4].replace("_", " ").capitalize())
                st.code(open(pick, encoding="utf-8", errors="replace").read(), language=None)
            else:
                st.info("No logs yet. Use Refresh results.")
        elif csv and os.path.exists(csv):
            data = _nice(pd.read_csv(csv))
            if it["tag"] == "Check":
                only_fail = st.checkbox("Show only failed checks")
                col = next((c for c in data.columns if c.lower() in ("passed", "pass", "ok", "result", "status", "success")), None)
                if only_fail and col:
                    data = data[~data[col].astype(str).str.strip().str.lower().isin(PASS_WORDS)]
                st.dataframe(data, hide_index=True, width="stretch")
            elif png:
                with st.expander("Show the data table"):
                    st.dataframe(data, hide_index=True, width="stretch")
            else:
                st.dataframe(data, hide_index=True, width="stretch")
        elif it["csv"]:
            st.info("This table has not been generated yet. Use Refresh results.")

        d1, d2, d3 = st.columns(3)
        if png and os.path.exists(png):
            d1.download_button("Download figure (PNG)", _read(png), os.path.basename(png), "image/png", type="primary", key=f"png_{i}", width="stretch")
        if csv and os.path.exists(csv):
            d2.download_button("Download data (CSV)", _read(csv), os.path.basename(csv), "text/csv", key=f"csv_{i}", width="stretch")
        if it["cap"]:
            st.caption("Suggested caption (edit to fit your report):")
            st.code(it["cap"], language=None)