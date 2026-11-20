"""pipeline_view.py - colour-coded pipeline diagram for the dashboard.

Parses the text produced by PipelineCPU.format_trace(n) into a grid
(rows = instructions, columns = cycles) like the Vercel pipeline simulator.

  IF/ID/EX/MEM/WB  stage colours
  STALL (grey)     instruction held in ID by the hazard unit (load-use etc.)
  FLUSH (hatched)  wrong-path instruction squashed after a branch/jump redirect
  yellow outline   operand forwarded into EX (inferred from the trace)

Usage in app.py:
    from pipeline_view import show_pipeline
    show_pipeline(cpu.format_trace(start + n - 1), forwarding=fwd, start=start)
"""
import html
import re

STAGES = ["IF", "ID", "EX", "MEM", "WB"]
COLORS = {"IF": "#3b82f6", "ID": "#22c55e", "EX": "#f08060", "MEM": "#a855f7", "WB": "#ef4444"}

NO_DEST = {"sw", "beq", "bne", "blt", "bge", "bltu", "bgeu", "ecall", "nop"}
NO_SRC = {"lui", "auipc", "jal", "ecall", "nop"}
_PC = re.compile(r"^([0-9a-fA-F]+):(.*)$")
_REG = re.compile(r"\bx(\d+)\b")


# ------------------------------------------------------------------ parsing
def _parse_cell(raw):
    raw = raw.strip()
    if raw in ("", "-"):
        return None
    if raw == "(held)":
        return {"held": True}
    squashed = raw.startswith("x ")
    if squashed:
        raw = raw[2:].strip()
    stall = raw.endswith("(stall)")
    if stall:
        raw = raw[:-len("(stall)")].strip()
    m = _PC.match(raw)
    pc, asm = (m.group(1), m.group(2).strip()) if m else ("", raw)
    return {"pc": pc, "asm": asm, "squashed": squashed, "stall": stall, "held": False}


def parse_trace(text):
    """Return [(cycle_number, [cell x5]), ...] using the column widths of the dashed line."""
    spans, cycles = None, []
    for ln in text.splitlines():
        s = ln.strip()
        if spans is None:
            if s.startswith("---") and set(s) <= set("- "):
                spans = [m.span() for m in re.finditer(r"-+", ln)]
            continue
        if len(spans) != 6 or not re.match(r"^\s*\d+\s", ln):
            continue
        try:
            n = int(ln[spans[0][0]:spans[0][1]])
            cells = [_parse_cell(ln[a:b]) for a, b in spans[1:-1]]
            cells.append(_parse_cell(ln[spans[-1][0]:]))
        except ValueError:
            continue
        cycles.append((n, cells))
    return cycles


def _regs(asm):
    """(mnemonic, destination register or None, [source registers])."""
    mn = asm.split()[0].lower() if asm else ""
    regs = [int(r) for r in _REG.findall(asm)]
    if mn in NO_DEST:
        return mn, None, regs
    if mn in NO_SRC:
        return mn, (regs[0] if regs else None), []
    return mn, (regs[0] if regs else None), regs[1:]


# ------------------------------------------------------------------ grid building
def build_grid(cycles, forwarding=True):
    """Follow each dynamic instruction through the stages.

    Returns (instructions, forwards). Each instruction: {"pc","asm","cells":{cycle:(stage_idx,kind)}}
    kind is "ok", "stall" or "flush". forwards: {(inst_idx, cycle): "x28 from WB"}.
    """
    insts, occ = [], {}
    prev = [None] * 5
    prev_id_stall = False

    for n, cells in cycles:
        cur = [None] * 5
        for s in range(5):
            c = cells[s]
            if c is None or c.get("held"):
                continue
            if s == 0:
                src = None
            elif s == 1:
                src = prev[1] if prev_id_stall else prev[0]
            elif s == 2:
                src = None if prev_id_stall else prev[1]
            else:
                src = prev[s - 1]
            if src is None:
                insts.append({"pc": c["pc"], "asm": c["asm"], "cells": {}, "squashed": False})
                src = len(insts) - 1
            kind = "flush" if c["squashed"] else ("stall" if c["stall"] else "ok")
            insts[src]["cells"][n] = (s, kind)
            if c["squashed"]:
                insts[src]["squashed"] = True
            cur[s] = src
        occ[n] = cur
        prev = cur
        prev_id_stall = bool(cells[1] and cells[1].get("stall"))

    forwards = {}
    if forwarding:
        for n, cur in occ.items():
            e = cur[2]
            if e is None or insts[e]["cells"][n][1] == "flush":
                continue
            _, _, srcs = _regs(insts[e]["asm"])
            for r in sorted(set(srcs) - {0}):
                for stage_idx, name in ((3, "MEM"), (4, "WB")):
                    p = cur[stage_idx]
                    if p is None or insts[p]["cells"][n][1] == "flush":
                        continue
                    if _regs(insts[p]["asm"])[1] == r:
                        forwards.setdefault((e, n), []).append(f"x{r} from {name}")
                        break
        forwards = {k: ", ".join(v) for k, v in forwards.items()}
    return insts, forwards


# ------------------------------------------------------------------ HTML
_CSS = """
body{margin:0;background:#0e1117;color:#e6e6e6;font-family:Inter,Segoe UI,system-ui,sans-serif}
.wrap{max-height:560px;overflow:auto;padding:8px}
table{border-collapse:separate;border-spacing:4px;font-size:12px}
th{color:#9aa4b2;font-weight:600;position:sticky;top:0;background:#0e1117;z-index:3;padding:2px 0}
td.lbl{position:sticky;left:0;z-index:2;background:#161b26;font-family:Consolas,monospace;
  padding:0 10px;min-width:210px;white-space:nowrap;border-radius:6px}
td.lbl.dead{color:#7b8494;text-decoration:line-through}
td.c{min-width:46px;height:30px;text-align:center;border-radius:6px;font-weight:700;
  color:#fff;background:#161b26}
td.stall{background:#8b8f98}
td.flush{background:repeating-linear-gradient(45deg,#4b1d1d,#4b1d1d 5px,#2a1010 5px,#2a1010 10px);
  color:#fca5a5;font-size:10px}
td.fwd{box-shadow:0 0 0 3px #facc15}
.legend{display:flex;gap:14px;flex-wrap:wrap;padding:8px 10px 0;font-size:12px;align-items:center}
.sw{display:inline-block;width:14px;height:14px;border-radius:4px;margin-right:5px;vertical-align:-2px}
"""


def render_html(insts, forwards, cycle_nums):
    legend = "".join(f'<span><span class="sw" style="background:{COLORS[s]}"></span>{s}</span>' for s in STAGES)
    legend += '<span><span class="sw" style="background:#8b8f98"></span>STALL</span>'
    legend += ('<span><span class="sw" style="background:repeating-linear-gradient(45deg,#4b1d1d,#4b1d1d 3px,'
               '#2a1010 3px,#2a1010 6px)"></span>FLUSH (wrong path)</span>')
    legend += '<span><span class="sw" style="box-shadow:0 0 0 2px #facc15;background:#161b26"></span>Forwarded</span>'

    head = "<tr><th></th>" + "".join(f"<th>C{n}</th>" for n in cycle_nums) + "</tr>"
    rows = []
    for i, ins in enumerate(insts):
        label = html.escape(f"{ins['pc']}: {ins['asm']}" if ins["pc"] else ins["asm"])
        tds = [f'<td class="lbl{" dead" if ins["squashed"] else ""}">{label}</td>']
        for n in cycle_nums:
            cell = ins["cells"].get(n)
            if cell is None:
                tds.append('<td class="c"></td>')
                continue
            s, kind = cell
            if kind == "stall":
                tds.append('<td class="c stall">STALL</td>')
            elif kind == "flush":
                tds.append(f'<td class="c flush" title="squashed in {STAGES[s]}">&#10005; {STAGES[s]}</td>')
            else:
                fw = forwards.get((i, n))
                cls = "c fwd" if fw else "c"
                title = f' title="forwarded: {html.escape(fw)}"' if fw else ""
                tds.append(f'<td class="{cls}" style="background:{COLORS[STAGES[s]]}"{title}>{STAGES[s]}</td>')
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return (f"<style>{_CSS}</style><div class='legend'>{legend}</div>"
            f"<div class='wrap'><table>{head}{''.join(rows)}</table></div>")


# ------------------------------------------------------------------ public entry point
def show_pipeline(trace_text, forwarding=True, start=1):
    """Render the pipeline grid in Streamlit (falls back to plain text if parsing fails)."""
    import streamlit as st
    import streamlit.components.v1 as components

    cycles = parse_trace(trace_text)
    if not cycles:
        st.code(trace_text, language=None)
        return
    all_insts, all_fw = build_grid(cycles, forwarding)
    cycle_nums = [n for n, _ in cycles if n >= start]
    keep = [i for i, x in enumerate(all_insts) if any(n in x["cells"] for n in cycle_nums)]
    insts = [all_insts[i] for i in keep]
    forwards = {(new, n): txt for new, old in enumerate(keep)
                for (o, n), txt in all_fw.items() if o == old}

    n_stall = sum(1 for x in insts for n, (s, k) in x["cells"].items() if k == "stall" and n in cycle_nums)
    n_flush = sum(1 for x in insts for n, (s, k) in x["cells"].items() if k == "flush" and n in cycle_nums)
    st.caption(f"Cycles {cycle_nums[0]} to {cycle_nums[-1]}: {n_stall} stall cell(s), "
               f"{n_flush} flushed cell(s), {len(forwards)} forwarded operand(s) "
               f"(forwarding is inferred from the trace).")
    height = min(640, 100 + 38 * len(insts))
    components.html(render_html(insts, forwards, cycle_nums), height=height, scrolling=True)