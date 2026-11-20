#!/usr/bin/env python3
"""
main.py - command-line entry point for the wildfire RISC-V project.

  python main.py test                         verify pipeline == golden model (all programs, all configs)
  python main.py asm FILE.s [FILE2.s ...]     assemble (files are concatenated) and print a listing
  python main.py run FILE.s [options]         run on golden model AND pipeline, print state + CPI
        --no-forwarding  --policy {stall,not_taken,bimodal}  --trace N  --sensors TEMP,SMOKE
  python main.py firmware {event,polling_naive,polling_validated} --sensors 65,45 [--trace N]
  python main.py soc [--scenario normal|heatwave|wildfire] [--seed N]
  python main.py experiments [--quick]
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from config import make_config
from sim.assembler import assemble_files
from sim.golden import GoldenCPU
from sim.isa import REG_NAMES
from sim.memory import Bus
from sim.pipeline import PipelineCPU
from sim.sensors import generate
from sim.soc import ASM_DIR, WildfireSoC


def parse_sensors(s):
    t, sm = s.split(",")
    return int(t), int(sm)


def cmd_test(a):
    from tests.run_tests import run_all
    _, ok = run_all(verbose=True)
    return 0 if ok else 1


def cmd_asm(a):
    defs = {"TEMP_THRESH": 60, "SMOKE_THRESH": 30, "REQUIRE_SMOKE": 1}
    for kv in (a.define or []):
        k, v = kv.split("=")
        defs[k] = int(v, 0)
    prog = assemble_files(a.files, defs)
    print(prog.dump())
    return 0


def show_regs(cpu):
    from sim.isa import s32
    for i in range(0, 32, 4):
        print("   " + "   ".join(f"x{j:<2}={cpu.regs[j]:#010x}" for j in range(i, i + 4)))


def cmd_run(a):
    defs = {"TEMP_THRESH": 60, "SMOKE_THRESH": 30, "REQUIRE_SMOKE": 1}
    prog = assemble_files([a.file], defs)
    t, s = parse_sensors(a.sensors)
    g = GoldenCPU(Bus(prog, t, s)).run()
    pbus = Bus(prog, t, s)
    p = PipelineCPU(pbus, forwarding=not a.no_forwarding, branch_policy=a.policy, trace=bool(a.trace)).run()
    print(f"golden model : {g.retired} instructions (CPI 1 by definition)")
    st = p.stats()
    print(f"pipeline     : {st['cycles']} cycles, {st['retired']} instructions, CPI {st['cpi']:.3f}")
    print(f"   data stalls {st['data_stalls']}, control penalty {st['control_penalty']}, forwards "
          f"{st['fwd_ex_mem']}+{st['fwd_mem_wb']}, branches {st['branches']} (mispredicted {st['mispredicts']})")
    print("same final state as golden model:", g.regs == p.regs)
    print("registers (pipeline):"); show_regs(p)
    if a.trace:
        print(p.format_trace(a.trace))
    return 0


def cmd_firmware(a):
    cfg = make_config()
    soc = WildfireSoC(cfg)
    t, s = parse_sensors(a.sensors)
    prog = soc.images[a.image]
    bus = Bus(prog, t, s)
    cpu = PipelineCPU(bus, forwarding=cfg["cpu"]["forwarding"], branch_policy=cfg["cpu"]["branch_policy"],
                      trace=bool(a.trace)).run()
    print(f"image={a.image}  sensors: temp={t} C smoke={s}")
    st = cpu.stats()
    print(f"core ran {st['cycles']} cycles ({st['retired']} instr, CPI {st['cpi']:.2f}) "
          f"= {st['cycles'] / cfg['cpu']['clock_hz'] * 1e6:.0f} us at {cfg['cpu']['clock_hz'] / 1e6:g} MHz")
    print("radio packet:", [hex(w) for _, w in bus.radio_log] or "none (no alert)")
    if a.trace:
        print(cpu.format_trace(a.trace))
    return 0


def cmd_soc(a):
    cfg = make_config(seed=a.seed)
    soc = WildfireSoC(cfg)
    scs = [a.scenario] if a.scenario else ["normal", "heatwave", "wildfire"]
    for sc in scs:
        st = generate(sc, cfg["duration_s"], cfg["sample_period_s"], a.seed)
        print(f"== {sc} (seed {a.seed}), ignition at {st.ignite_s}")
        for m in WildfireSoC.MODES:
            r = soc.summarize(soc.simulate(m, st))
            lat = f"{r['latency_s']:.1f} s" if r["latency_s"] is not None else "-"
            print(f"  {m:<18} {r['energy_j'] * 1e3:9.2f} mJ/day  {r['avg_power_uw']:7.2f} uW  wakeups={r['core_wakeups']:5d} "
                  f"idle={r['idle_wakeups']:5d} tx={r['transmissions']:4d} falseTX={r['false_transmissions']:3d} latency={lat}")
    return 0


def cmd_experiments(a):
    import experiments
    return 0 if experiments.run_all_experiments(quick=a.quick) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("test").set_defaults(fn=cmd_test)
    p = sub.add_parser("asm"); p.add_argument("files", nargs="+"); p.add_argument("--define", nargs="*", help="NAME=VALUE"); p.set_defaults(fn=cmd_asm)
    p = sub.add_parser("run"); p.add_argument("file")
    p.add_argument("--no-forwarding", action="store_true")
    p.add_argument("--policy", default="not_taken", choices=PipelineCPU.POLICIES)
    p.add_argument("--trace", type=int, default=0, metavar="N", help="print first N cycles of the pipeline diagram")
    p.add_argument("--sensors", default="0,0"); p.set_defaults(fn=cmd_run)
    p = sub.add_parser("firmware"); p.add_argument("image", choices=WildfireSoC.MODES)
    p.add_argument("--sensors", default="65,45"); p.add_argument("--trace", type=int, default=0)
    p.set_defaults(fn=cmd_firmware)
    p = sub.add_parser("soc"); p.add_argument("--scenario", choices=["normal", "heatwave", "wildfire"])
    p.add_argument("--seed", type=int, default=1); p.set_defaults(fn=cmd_soc)
    p = sub.add_parser("experiments"); p.add_argument("--quick", action="store_true")
    p.set_defaults(fn=cmd_experiments)
    a = ap.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
