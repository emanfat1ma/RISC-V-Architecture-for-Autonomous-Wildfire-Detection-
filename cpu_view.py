"""cpu_view.py - RISC-V core tab: the wake-up firmware on a conveyor belt (uses the real pipeline trace)."""
import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from config import CONFIG
from pipeline_view import parse_trace
from sim.memory import Bus
from sim.pipeline import PipelineCPU

STEPS = [("Boot", 0x00, "The CPU was fully off, so it starts from scratch: set the stack and clear 16 words of scratch memory."),
         ("Read sensors", 0x28, "Read the temperature and smoke values from the sensor registers."),
         ("Score", 0x34, "Work out how serious it is: degrees over the limit plus smoke, each divided by 8."),
         ("Classify", 0x50, "Turn the score into a severity class from 0 (low) to 3 (critical)."),
         ("Build packet", 0x78, "Write the alert packet to memory: magic tag, temperature, smoke, class."),
         ("Send", 0x98, "Push each word to the radio while adding up a checksum."),
         ("Sleep", 0xC0, "Send the checksum and tell the SoC to power the CPU off.")]
NAMES = {"event": "Wake-up handler (event-driven)", "polling_naive": "Polling node (naive)",
         "polling_validated": "Polling node (validated)"}


def _run(prog, t, s, fwd, pol, trace=True):
    bus = Bus(prog, t, s)
    return PipelineCPU(bus, forwarding=fwd, branch_policy=pol, trace=trace).run(), bus


def show_cpu(soc, fwd, policy):
    c1, c2, c3 = st.columns(3)
    image = c1.selectbox("Firmware", list(soc.images), format_func=lambda m: NAMES.get(m, m))
    temp = int(c2.number_input("Temperature sensor (°C)", 0, 255, 65))
    smoke = int(c3.number_input("Smoke sensor", 0, 100, 45))
    prog = soc.images[image]
    cpu, bus = _run(prog, temp, smoke, fwd, policy)
    s = cpu.stats()
    for col, (l, v) in zip(st.columns(4), (("Cycles", s["cycles"]), ("Instructions", s["retired"]), ("CPI", f"{s['cpi']:.2f}"),
                                           ("Time at clock", f"{s['cycles'] / CONFIG['cpu']['clock_hz'] * 1e6:.0f} µs"))):
        col.metric(l, v)

    cycles = parse_trace(cpu.format_trace())
    rows = [[None if c is None else (["", "(held)", "h"] if c.get("held") else
                                     [c["pc"], c["asm"], "x" if c["squashed"] else "s" if c["stall"] else ""]) for c in cells]
            for _, cells in cycles]
    steps = []
    if image == "event":
        for name, addr, cap in STEPS:
            steps.append([name, next((i for i, r in enumerate(rows) if r[0] and r[0][0] and r[0][2] != "x"
                                      and int(r[0][0], 16) == addr), None), cap])
    components.html(HTML.replace("__DATA__", json.dumps({"rows": rows, "steps": steps}, separators=(",", ":"))), height=400)

    words = [w for _, w in bus.radio_log]
    if image == "event" and len(words) == 5:
        boot = steps[1][1] or 0
        st.markdown(f"**Cost of waking up:** about {boot} cycles of cold boot, then {s['cycles'] - boot} cycles for the alert routine. "
                    "Power gating wipes the CPU, so every wake starts from boot.")
        labels = ["magic", "temp", "smoke", "class", "checksum"]
    else:
        labels = [f"word {i + 1}" for i in range(len(words))]
    st.markdown("**Radio packet**")
    if words:
        for col, l, w in zip(st.columns(len(words)), labels, words):
            col.metric(l, hex(w))
    else:
        st.caption("No packet: these sensor values do not raise an alert.")

    cpis = {}
    for f_ in (True, False):
        for pol in PipelineCPU.POLICIES:
            c_, _ = _run(prog, temp, smoke, f_, pol, False)
            cpis[f"Forwarding {'on' if f_ else 'off'}, {pol}"] = c_.stats()["cpi"]
    st.markdown("**Same firmware, six pipeline settings (CPI, lower is better)**")
    st.bar_chart(pd.Series(cpis, name="CPI"), horizontal=True)


HTML = r"""<!doctype html><meta charset="utf-8"><style>
body{margin:0;background:#111a1a;color:#e8efe9;font:14px system-ui,'Segoe UI',sans-serif;padding:6px}
button{border:0;border-radius:16px;padding:7px 13px;font:700 12px inherit;cursor:pointer;background:#243433;color:#e8efe9;margin:0 6px 6px 0}
button.on{background:#f2b84b;color:#1b1209}.bar{display:flex;gap:8px;align-items:center;margin-top:6px}input{flex:1;accent-color:#f2b84b}
#st{display:grid;grid-template-columns:repeat(5,1fr);gap:26px;margin-top:10px}.stn{background:#243433;border:2px solid;border-radius:14px;overflow:hidden;height:120px}
.hd{padding:7px;text-align:center;font-weight:700;color:#10150f}.blk{margin:12px;border-radius:10px;height:62px;display:flex;flex-direction:column;align-items:center;justify-content:center;font-weight:700;font-size:13px;text-align:center}
.blk small{font-size:11px;margin-top:3px}#cap{margin:10px 2px;color:#f2b84b;font-size:15px;min-height:22px}</style>
<div id=chips></div><div id=st></div><div id=cap></div>
<div class=bar><button id=play>Play</button><button id=bk>Back</button><button id=fw>Step</button><input id=scr type=range min=0 value=0><span id=cl></span></div>
<script>
const D=__DATA__,$=i=>document.getElementById(i),ST=[['IF','Fetch','#3b82f6'],['ID','Decode','#22c55e'],['EX','Execute','#f08060'],['MEM','Memory','#a855f7'],['WB','Write back','#ef4444']];
let c=0,timer=null;
function cur(){let k=-1;D.steps.forEach((s,j)=>{if(s[1]!==null&&s[1]<=c)k=j});return k}
function draw(){const r=D.rows[c],k=cur();
$('chips').innerHTML=D.steps.map((s,j)=>`<button class="${j===k?'on':''}" data-j=${j}>${j+1} ${s[0]}</button>`).join('');
$('cap').textContent=k>=0?D.steps[k][2]:'';
$('st').innerHTML=ST.map((s,j)=>{const x=r[j];let b='<div class=blk style="border:2px dashed #93a39e;color:#93a39e">empty</div>';
if(x){const n=x[1];if(x[2]==='x')b=`<div class=blk style="border:2px dashed #ff6a3d;background:#3a1b14;color:#ffb199">${n}<small>FLUSHED</small></div>`;
else if(x[2]==='s')b=`<div class=blk style="background:#6b727a">${n}<small>STALL</small></div>`;
else if(x[2]==='h')b='<div class=blk style="border:2px dashed #93a39e;color:#93a39e">fetch held</div>';
else b=`<div class=blk style="background:${s[2]};color:#10150f">${n}</div>`}
return `<div class=stn style="border-color:${s[2]}"><div class=hd style="background:${s[2]}">${s[0]} ${s[1]}</div>${b}</div>`}).join('');
$('scr').value=c;$('cl').textContent='Cycle '+(c+1)+' / '+D.rows.length}
$('scr').max=D.rows.length-1;$('scr').oninput=e=>{c=+e.target.value;draw()};
$('fw').onclick=()=>{c=Math.min(D.rows.length-1,c+1);draw()};$('bk').onclick=()=>{c=Math.max(0,c-1);draw()};
$('play').onclick=()=>{if(timer){clearInterval(timer);timer=null;$('play').textContent='Play'}else{$('play').textContent='Pause';timer=setInterval(()=>{if(c>=D.rows.length-1){$('play').click();return}c++;draw()},300)}};
$('chips').onclick=e=>{const j=e.target.dataset.j;if(j!==undefined&&D.steps[j][1]!==null){c=D.steps[j][1];draw()}};
draw();
</script>"""