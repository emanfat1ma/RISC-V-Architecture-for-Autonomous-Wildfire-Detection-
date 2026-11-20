"""mission_control.py - animated Mission control replay for the dashboard (Pass 1).

Everything shown comes from the real simulator results already computed in app.py
(stream, acts, summ). Usage, as the first lines inside `with tab1:` in app.py:

    from mission_control import show_mission
    show_mission(stream, acts, summ, T, S, persist, hold, poll_s)
"""
import json

import streamlit.components.v1 as components


def build_payload(stream, acts, summ, T, S, persist, hold, poll_s):
    ev = acts["event"]["events"]
    E, seen_fire = [], False
    for e in ev:
        if not e["fire"]:
            k = "wake_false"
        elif not seen_fire:
            k, seen_fire = "wake_fire", True
        else:
            k = "wake_re"
        E.append([round(e["t"], 1), k])
    if stream.ignite_s is not None:
        E.append([round(stream.ignite_s, 1), "ign"])
    pv = []
    for e in acts["polling_validated"]["events"]:
        if e["tx"]:
            pv.append(round(e["t"], 1))
            E.append([round(e["t"], 1), "pv_true" if e["fire"] else "pv_false"])
    for e in acts["polling_naive"]["events"]:
        if e["tx"] and not e["fire"]:
            E.append([round(e["t"], 1), "pn_false"])
    E.sort(key=lambda x: x[0])

    def cost(m):
        r = summ[m]
        return {"always": r["always_on_j"], "var": r["wake_j"] + r["cpu_j"] + r["sensing_j"], "radio": r["radio_j"],
                "n": r["core_wakeups"], "tx": r["transmissions"], "total": r["energy_j"]}

    return {"temp": list(stream.temp), "smoke": list(stream.smoke), "dt": stream.dt,
            "T": T, "S": S, "P": persist, "H": hold, "poll": poll_s, "E": E,
            "wake": [round(e["t"], 1) for e in ev], "pv": pv, "dur": len(stream) * stream.dt,
            "ign": stream.ignite_s, "ev": cost("event"), "po": cost("polling_validated")}


def show_mission(stream, acts, summ, T, S, persist, hold, poll_s, height=1060):
    data = build_payload(stream, acts, summ, T, S, persist, hold, poll_s)
    html = HTML.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    components.html(html, height=height, scrolling=False)
    show_verdicts(summ)


def show_verdicts(summ):
    import streamlit as st
    ev, pv, pn = summ["event"], summ["polling_validated"], summ["polling_naive"]
    cards = [(f"{(1 - ev['energy_j'] / pv['energy_j']) * 100:.0f}%", "less energy than polling", f"{ev['energy_j'] * 1e3:.0f} vs {pv['energy_j'] * 1e3:.0f} mJ today", "#6fbf8a"),
             (f"{pv['core_wakeups']} to {ev['core_wakeups']}", "CPU wake-ups", "polling vs event-driven", "#f2b84b"),
             (f"{pn['false_transmissions']} vs {ev['false_transmissions']}", "false alerts", "naive polling vs event-driven", "#ff6a3d")]
    if ev["latency_s"] is not None and pv["latency_s"] is not None:
        cards.append((f"{pv['latency_s'] - ev['latency_s']:.0f} s", "faster detection", f"{ev['latency_s']:.0f} s vs {pv['latency_s']:.0f} s", "#5aa9e6"))
    elif ev["missed_fire"]:
        cards.append(("missed", "the fire was not detected", "try lower limits", "#ff6a3d"))
    for col, (big, lab, sub, c) in zip(st.columns(len(cards)), cards):
        col.markdown(f'<div style="background:#1a2625;border-left:8px solid {c};border-radius:14px;padding:14px 18px"><div style="font-size:32px;font-weight:700;color:{c}">{big}</div><div style="font-weight:700;color:#e8efe9">{lab}</div><div style="color:#93a39e;font-size:13px">{sub}</div></div>', unsafe_allow_html=True)


HTML = r"""<!doctype html><meta charset="utf-8"><style>
:root{--p:#1a2625;--p2:#243433;--tx:#e8efe9;--mu:#93a39e;--em:#ff6a3d;--am:#f2b84b;--mo:#6fbf8a;--sl:#3a4a48;--bl:#5aa9e6}
*{box-sizing:border-box}body{margin:0;background:#111a1a;color:var(--tx);font:14px system-ui,'Segoe UI',sans-serif;padding:6px}
.bar{display:flex;gap:10px;align-items:center;background:var(--p);border-radius:18px;padding:8px 14px}
button,select{border:0;border-radius:16px;padding:7px 14px;font:700 13px inherit;cursor:pointer;background:var(--p2);color:var(--tx)}
button.on{background:var(--mo);color:#10201a}input[type=range]{flex:1;accent-color:var(--am)}
#clock{font-size:22px;font-weight:700;min-width:92px;text-align:right}
#banner{margin-top:10px;border-radius:20px;border:3px solid;display:flex;align-items:center;gap:22px;padding:14px 22px;transition:background .3s,border-color .3s}
#banner h1{margin:0;font-size:32px}#banner p{margin:5px 0 0;color:var(--mu);font-size:15px}
.grid{display:grid;grid-template-columns:1.5fr 1fr;gap:10px;margin-top:10px}.card{background:var(--p);border-radius:18px;padding:14px}
h3{margin:0 0 10px;font-size:15px}.mt{height:22px;background:var(--sl);border-radius:11px;position:relative;margin:4px 0 16px}
.mt i{display:block;height:100%;border-radius:11px;background:var(--mo)}.mt b{position:absolute;top:-4px;width:2px;height:30px;background:#fff}
.lab{display:flex;justify-content:space-between;color:var(--mu);font-size:13px}.lab span:last-child{color:var(--tx);font-weight:700;font-size:16px}
#feed div{display:flex;gap:9px;margin:0 0 9px;line-height:1.3}#feed small{color:var(--mu);min-width:60px}#feed u{width:11px;height:11px;border-radius:50%;margin-top:3px;flex:none}
.twin{display:grid;grid-template-columns:1fr 1fr;gap:10px}.node{background:var(--p2);border-radius:14px;padding:12px 14px;display:flex;gap:14px}
.lamp{width:34px;height:34px;border-radius:50%;background:#0b1010;border:2px solid var(--sl);flex:none;margin-top:4px}
.node h4{margin:0 0 4px;font-size:15px}.node .n{font-size:24px;font-weight:700}.ebar{height:12px;background:var(--sl);border-radius:6px;margin:4px 0}
.ebar i{display:block;height:100%;border-radius:6px}.mu{color:var(--mu);font-size:12px}</style>
<div class=bar><button id=play class=on>Pause</button><button id=next>Next event</button>
<select id=mul><option value=.5>0.5x</option><option value=1 selected>1x</option><option value=2>2x</option><option value=4>4x</option></select>
<button id=snd>Enable sound</button><input id=scr type=range min=0 max=1 value=0 step=1><div id=clock></div></div>
<div id=banner><svg id=ring width=110 height=110 viewBox="0 0 110 110"></svg><div><h1 id=bt></h1><p id=bd></p></div></div>
<div class=card style="margin-top:10px;padding:0;overflow:hidden"><svg id=scene viewBox="0 0 900 170" width=100%></svg></div>
<div class=grid><div class=card><h3>Inside the node</h3>
<svg id=chip viewBox="0 0 900 215" width=100% font-family="system-ui,Segoe UI,sans-serif">
<rect x=5 y=15 width=150 height=170 rx=14 fill=#243433 /><text x=20 y=43 fill=#e8efe9 font-weight=700>Sensors</text>
<text x=20 y=74 fill=#93a39e font-size=12>Temperature</text><text id=vt x=20 y=102 fill=#e8efe9 font-size=24 font-weight=700></text>
<text x=20 y=136 fill=#93a39e font-size=12>Smoke</text><text id=vs x=20 y=164 fill=#e8efe9 font-size=24 font-weight=700></text>
<line id=w1 x1=155 y1=100 x2=200 y2=100 stroke=#3a4a48 stroke-width=4 /><line id=w2 x1=370 y1=100 x2=420 y2=100 stroke=#3a4a48 stroke-width=4 />
<line id=w3 x1=590 y1=100 x2=650 y2=100 stroke=#3a4a48 stroke-width=4 />
<rect id=b1 x=200 y=15 width=170 height=170 rx=14 fill=#243433 stroke=#3a4a48 stroke-width=3 /><text x=215 y=43 fill=#e8efe9 font-weight=700>Tier 1 sentry</text>
<text x=215 y=62 fill=#93a39e font-size=12>always on, analog</text><text id=t1s x=215 y=105 fill=#e8efe9 font-weight=700></text><text id=t1l x=215 y=160 fill=#93a39e font-size=12></text>
<rect id=b2 x=420 y=15 width=170 height=170 rx=14 fill=#243433 stroke=#3a4a48 stroke-width=3 /><text x=435 y=43 fill=#e8efe9 font-weight=700>Tier 2 controller</text>
<text x=435 y=62 fill=#93a39e font-size=12>always on, digital</text><text id=t2s x=435 y=105 fill=#e8efe9 font-weight=700></text><g id=sq></g>
<rect id=b3 x=650 y=15 width=245 height=170 rx=14 fill=#0b1010 stroke=#3a4a48 stroke-width=3 stroke-dasharray="7 6" /><text id=t3h x=665 y=43 fill=#e8efe9 font-weight=700>Tier 3 RISC-V CPU</text>
<g id=pills opacity=0></g><text id=t3s x=665 y=160 fill=#93a39e font-size=13></text><circle id=pulse cx=505 cy=100 r=9 fill=#ffe2a3 opacity=0 /></svg>
<div class=lab><span>Temperature</span><span id=mT></span></div><div class=mt><i id=fT></i><b id=lT></b></div>
<div class=lab><span>Smoke</span><span id=mS></span></div><div class=mt><i id=fS></i><b id=lS></b></div></div>
<div class=card><h3>Node activity</h3><div id=feed></div></div></div>
<div class=card style="margin-top:10px"><h3>Same day, two nodes</h3><div class=twin>
<div class=node><div class=lamp id=lE></div><div style="flex:1"><h4>Event-driven</h4><div class=mu>CPU wake-ups so far</div><div class=n id=wE></div>
<div class=mu>Energy used so far</div><div class=ebar><i id=eE style="background:#6fbf8a"></i></div><div class=mu id=jE></div></div></div>
<div class=node><div class=lamp id=lP></div><div style="flex:1"><h4 id=hP></h4><div class=mu>CPU wake-ups so far</div><div class=n id=wP></div>
<div class=mu>Energy used so far</div><div class=ebar><i id=eP style="background:#f2b84b"></i></div><div class=mu id=jP></div></div></div></div></div>
<script>
const D=__DATA__,$=i=>document.getElementById(i),N=D.temp.length,Et=D.E.map(e=>e[0]),keyT=D.E.filter(e=>e[1]!=='pn_false').map(e=>e[0]);
const hh=x=>{x=Math.floor(x);return[Math.floor(x/3600),Math.floor(x%3600/60),x%60].map(v=>String(v).padStart(2,'0')).join(':')};
const ub=(a,x)=>{let lo=0,hi=a.length;while(lo<hi){const m=(lo+hi)>>1;if(a[m]<=x)lo=m+1;else hi=m}return lo};
const COL={SAFE:['#6fbf8a','#16281f'],SUSPECT:['#f2b84b','#33291a'],VALIDATING:['#ff9a3d','#33231a'],CONFIRMED:['#ff6a3d','#3a1b14'],COOLDOWN:['#5aa9e6','#14283a']};
const K={ign:['#3a4a48',"Fire starts (the node can't see this)"],wake_fire:['#ff6a3d','Tier 2 confirmed. WAKE_UP sent, the CPU sent the alert'],
wake_re:['#ff6a3d','Fire still burning: the CPU woke and re-sent the alert'],wake_false:['#f2b84b','False wake: Tier 2 confirmed but no fire is burning'],
pv_true:['#f2b84b','Polling node finally checks and sends its alert'],pv_false:['#ff6a3d','Validated polling node sent a false alert'],pn_false:['#ff6a3d','Naive polling node sent a false alert']};
const SND={wake_fire:'siren',wake_re:'chirp',wake_false:'buzz',pv_true:'pollOk',pv_false:'buzz',pn_false:'buzz'};
let ac=null,sndOn=false,t=0,playing=true,mul=1,ei=0,flE=0,flP=0,lastSnd=0,last=performance.now(),feed=[];
function tone(f,d,ty,g,sw){if(!ac)return;const o=ac.createOscillator(),a=ac.createGain(),n=ac.currentTime;o.type=ty;o.frequency.setValueAtTime(f,n);
if(sw)o.frequency.linearRampToValueAtTime(f+sw,n+d);a.gain.setValueAtTime(g,n);a.gain.exponentialRampToValueAtTime(.0001,n+d);o.connect(a);a.connect(ac.destination);o.start();o.stop(n+d)}
const sounds={siren(){[0,550,1100].forEach(k=>setTimeout(()=>tone(650,.5,'square',.12,550),k))},chirp(){tone(1100,.15,'square',.08,0)},
buzz(){tone(110,.5,'sawtooth',.2,0)},pollOk(){tone(520,.25,'triangle',.15,0);setTimeout(()=>tone(390,.35,'triangle',.15,0),260)}};
function addFeed(e){feed.unshift(`<div><u style="background:${K[e[1]][0]}"></u><small>${hh(e[0])}</small><span>${K[e[1]][1]}</span></div>`);feed=feed.slice(0,7);$('feed').innerHTML=feed.join('')}
function fire(e){addFeed(e);if(e[1].startsWith('wake'))flE=1;const s=SND[e[1]],now=performance.now();
if(sndOn&&s&&(now-lastSnd>600||s==='siren')){sounds[s]();lastSnd=now}}
function seek(x){t=Math.max(0,Math.min(D.dur,x));ei=ub(Et,t);feed=[];for(let k=Math.max(0,ei-7);k<ei;k++)addFeed(D.E[k]);flE=0}
function speed(x){const i=ub(keyT,x),nx=i<keyT.length?keyT[i]-x:1e9,pv=i>0?x-keyT[i-1]:1e9;return(nx<60||pv<45)?4:1500}
function stateAt(x){const i=Math.min(N-1,Math.floor(x/D.dt)),lw=ub(D.wake,x)-1,since=lw>=0?x-D.wake[lw]:1e9,hot=D.temp[i]>D.T,smk=D.smoke[i]>=D.S;
if(since<15)return{s:'CONFIRMED',cnt:D.P,i,hot,smk};if(since<D.H)return{s:'COOLDOWN',cnt:0,left:D.H-since,i,hot,smk};
let c=0;for(let k=i;k>=0&&c<D.P;k--){if(D.temp[k]>D.T&&D.smoke[k]>=D.S)c++;else break}
if(lw>=0)c=Math.min(c,Math.max(0,Math.floor(since-D.H)+1));c=Math.min(c,D.P-1);
return c>0?{s:'VALIDATING',cnt:c,i,hot,smk}:{s:hot?'SUSPECT':'SAFE',cnt:0,i,hot,smk}}
function words(s){const f=D.ign!==null&&t>=D.ign,tp=D.temp[s.i],sm=D.smoke[s.i];
if(s.s==='SAFE')return['All quiet',`Temperature ${tp} °C and smoke ${sm} are normal. The CPU is off.`];
if(s.s==='SUSPECT')return['Heat only, not a fire',`Temperature is over ${D.T} °C, but smoke is ${sm} (needs ${D.S}). Tier 2 says no, so the CPU stays off.`];
if(s.s==='VALIDATING')return['Checking it is real',`Heat and smoke are both high. Counting ${s.cnt} of ${D.P} samples in a row.`];
if(s.s==='CONFIRMED')return f?['Fire confirmed','Tier 2 woke the CPU. It sends the alert and goes back to sleep.']:['False wake','Tier 2 was fooled: heat and smoke persisted but no fire is burning.'];
return['Alert sent, cooling down',`Tier 2 is paused for ${Math.ceil(s.left)} s so one fire does not flood the radio.`]}
const STG=[['IF','#3b82f6'],['ID','#22c55e'],['EX','#f08060'],['MEM','#a855f7'],['WB','#ef4444']];
$('pills').innerHTML=STG.map((p,k)=>`<rect x=${665+k*45} y=95 width=41 height=26 rx=6 fill=${p[1]} /><text x=${685.5+k*45} y=113 text-anchor=middle font-size=11 font-weight=700 fill=#10150f>${p[0]}</text>`).join('');
function energy(c,w,tx){return c.always*(t/D.dur)+c.var*(w/Math.max(1,c.n))+c.radio*(tx/Math.max(1,c.tx))}
function render(){const s=stateAt(t),[bt,bd]=words(s),[c,bg]=COL[s.s],B=$('banner'),i=s.i,P=D.P;
B.style.borderColor=c;B.style.background=bg;$('bt').textContent=bt;$('bd').textContent=bd;
let r='';const gap=P>12?2:5,span=360/P-2*gap;
for(let k=0;k<P;k++){const a0=(-90+360/P*k+gap)*Math.PI/180,a1=a0+span*Math.PI/180,on=k<s.cnt;
r+=`<path d="M${55+44*Math.cos(a0)} ${55+44*Math.sin(a0)} A44 44 0 ${span>180?1:0} 1 ${55+44*Math.cos(a1)} ${55+44*Math.sin(a1)}" fill=none stroke="${on?c:'#3a4a48'}" stroke-width=11 stroke-linecap=round />`}
$('ring').innerHTML=r+`<text x=55 y=63 text-anchor=middle fill=#e8efe9 font-size=24 font-weight=700>${s.cnt}/${P}</text>`;
$('clock').textContent=hh(t);$('scr').value=t;
const hotC=s.hot?(s.smk?'#ff6a3d':'#f2b84b'):'#3a4a48';
$('vt').textContent=D.temp[i]+' °C';$('vs').textContent=D.smoke[i];$('b1').setAttribute('stroke',hotC);$('w1').setAttribute('stroke',hotC);
$('t1s').textContent=s.hot?'Over limit':'Below limit';$('t1l').textContent='limit: '+D.T+' °C';
const t2={SAFE:'Idle',SUSPECT:'Smoke too low',VALIDATING:'Validating',CONFIRMED:'Confirmed',COOLDOWN:'Cooling down'}[s.s];
$('t2s').textContent=t2;$('b2').setAttribute('stroke',s.s==='SAFE'||s.s==='SUSPECT'?'#3a4a48':c);$('w2').setAttribute('stroke',s.s==='SAFE'?'#3a4a48':c);
let q='';for(let k=0;k<P;k++)q+=`<rect x=${435+k*(150/P)} y=130 width=${Math.max(4,150/P-4)} height=18 rx=4 fill="${k<s.cnt?c:'#33423f'}" />`;
$('sq').innerHTML=q+`<text x=435 y=170 fill=#93a39e font-size=12>persistence ${s.cnt}/${P}</text>`;
const lit=flE>.05;$('b3').setAttribute('fill',lit?'#1f3a2a':'#0b1010');$('b3').setAttribute('stroke',lit?'#6fbf8a':'#3a4a48');
$('b3').setAttribute('stroke-dasharray',lit?'0':'7 6');$('pills').setAttribute('opacity',lit?1:0);$('w3').setAttribute('stroke',lit?'#ff6a3d':'#3a4a48');
$('t3s').textContent=lit?'Awake: sending alert':'Power-gated (off)';const pu=$('pulse');pu.setAttribute('opacity',lit?1:0);pu.setAttribute('cx',505+145*(1-flE));
$('mT').textContent=D.temp[i]+' °C';$('mS').textContent=D.smoke[i];$('fT').style.width=Math.min(100,D.temp[i]/120*100)+'%';$('fS').style.width=Math.min(100,D.smoke[i])+'%';
$('fT').style.background=D.temp[i]>D.T?'#ff6a3d':'#6fbf8a';$('fS').style.background=D.smoke[i]>=D.S?'#ff6a3d':'#6fbf8a';
$('lT').style.left=(D.T/120*100)+'%';$('lS').style.left=D.S+'%';
const wE=ub(D.wake,t),wP=Math.min(D.po.n,Math.floor(t/D.poll)+1),eE=energy(D.ev,wE,wE),eP=energy(D.po,wP,ub(D.pv,t));
$('wE').textContent=wE;$('wP').textContent=wP;$('hP').textContent='Polling every '+D.poll+' s';
$('eE').style.width=Math.max(1,eE/D.po.total*100)+'%';$('eP').style.width=Math.max(1,eP/D.po.total*100)+'%';
$('jE').textContent=(eE*1e3).toFixed(1)+' mJ';$('jP').textContent=(eP*1e3).toFixed(1)+' mJ';
$('lE').style.background=lit?'#6fbf8a':'#0b1010';$('lE').style.boxShadow=lit?'0 0 18px #6fbf8a':'none';
$('lP').style.background=flP>.1?'#f2b84b':'#0b1010';$('lP').style.boxShadow=flP>.1?'0 0 14px #f2b84b':'none';drawScene(s,i)}
const TR=[];for(let k=0;k<18;k++)TR.push([25+k*50+(k%3)*9,125+(k%2)*10,55+(k*37%30)]);
function drawScene(s,i){const tp=D.temp[i],sm=D.smoke[i],hot=Math.min(1,Math.max(0,(tp-25)/55)),f=D.ign!==null&&t>=D.ign,fl=f?Math.min(1,(t-D.ign)/25):0;
let h=`<rect width=900 height=170 fill="rgb(${Math.round(27+80*hot+40*fl)},${Math.round(42-8*hot)},${Math.round(48-20*hot)})"/><ellipse cx=640 cy=70 rx=220 ry=60 fill=#b0b8b4 opacity="${Math.min(.6,sm/150)}"/>`;
h+=TR.map(a=>`<polygon points="${a[0]},${a[1]-a[2]} ${a[0]-a[2]*.3},${a[1]} ${a[0]+a[2]*.3},${a[1]}" fill=#1d3a2b />`).join('');
h+='<path d="M0 135 Q300 120 600 135 T900 130 V170 H0Z" fill=#0f1a14 />';
for(const x of [560,610,660,710])h+=`<path d="M${x} 140 C${x-14} 118 ${x-6} 100 ${x} 82 C${x+6} 100 ${x+16} 118 ${x} 140Z" fill=#ff6a3d opacity="${fl}"/>`;
h+=`<rect x=118 y=88 width=4 height=60 fill=#3b2f26 /><rect x=102 y=70 width=36 height=24 rx=5 fill=#243433 stroke=#6fbf8a stroke-width=2 /><circle cx=130 cy=76 r=3 fill="${flE>.05?'#ff6a3d':'#6fbf8a'}"/>`;
if(flE>.05)h+=[16,28,40].map(r=>`<path d="M${120-r} 62 A${r} ${r} 0 0 1 ${120+r} 62" fill=none stroke=#ff6a3d stroke-width=3 opacity="${flE}"/>`).join('');
$('scene').innerHTML=h+`<text x=14 y=24 fill=#e8efe9 font-size=14 font-weight=700>${tp} °C   smoke ${sm}</text>`}
function tick(now){const dtr=Math.min(.1,(now-last)/1000);last=now;
if(playing&&t<D.dur){const t0=t;t=Math.min(D.dur,t+speed(t)*mul*dtr);while(ei<D.E.length&&D.E[ei][0]<=t){fire(D.E[ei]);ei++}
if(Math.floor(t/D.poll)>Math.floor(t0/D.poll))flP=1}
flE*=Math.pow(.5,dtr/.6);flP*=Math.pow(.5,dtr/.12);render();requestAnimationFrame(tick)}
$('scr').max=D.dur;$('scr').oninput=e=>seek(+e.target.value);
$('play').onclick=()=>{playing=!playing;$('play').textContent=playing?'Pause':'Play';$('play').className=playing?'on':''};
$('mul').onchange=e=>mul=+e.target.value;
$('next').onclick=()=>{const i=ub(keyT,t+30);if(i<keyT.length)seek(keyT[i]-20)};
$('snd').onclick=()=>{ac=ac||new (window.AudioContext||window.webkitAudioContext)();ac.resume();sndOn=!sndOn;$('snd').textContent=sndOn?'Sound on':'Enable sound';$('snd').className=sndOn?'on':'';if(sndOn)tone(660,.15,'sine',.1,0)};
seek(0);requestAnimationFrame(tick);
</script>"""