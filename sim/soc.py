"""
soc.py - The whole wildfire SoC (Steps 5-9 glued together).

  EventDrivenSoC : Tier1 -> Tier2 -> WAKE_UP -> power-gated RISC-V core (boot + handler)
  Polling nodes  : timer wakes the core every `poll.period_s`; the *firmware* decides
                   ('polling_naive' = temperature only, 'polling_validated' = temp AND smoke)

Every core activation runs the real firmware on the cycle-accurate pipeline, so the
cycle counts that feed the energy model are measured, not guessed.
"""
import os

from .assembler import assemble_files
from .energy import battery_energy_j, compute_energy, lifetime_years
from .memory import Bus
from .pipeline import PipelineCPU
from .tiers import Tier1, Tier2

ASM_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "asm")


class WildfireSoC:
    MODES = ("event", "polling_naive", "polling_validated")

    def __init__(self, cfg):
        self.cfg = cfg
        th = cfg["thresholds"]
        defs = {"TEMP_THRESH": th["temp_c"], "SMOKE_THRESH": th["smoke"], "REQUIRE_SMOKE": 1}
        common, boot = f"{ASM_DIR}/common.s", f"{ASM_DIR}/boot.s"
        handler, poll = f"{ASM_DIR}/handler.s", f"{ASM_DIR}/poll.s"
        self.images = {
            "event": assemble_files([common, boot, handler], defs),
            "polling_naive": assemble_files([common, poll, handler], {**defs, "REQUIRE_SMOKE": 0}),
            "polling_validated": assemble_files([common, poll, handler], defs),
        }
        self._cache = {}

    # ------------------------------------------------------------ core activation
    def run_core(self, mode, temp, smoke):
        """Power up the core, run the firmware until it requests sleep. Cached by inputs."""
        key = (mode, temp, smoke)
        if key in self._cache:
            return self._cache[key]
        prog = self.images[mode]
        bus = Bus(prog, temp, smoke)
        c = self.cfg["cpu"]
        hpc = prog.labels["handler_main"]
        cpu = PipelineCPU(bus, forwarding=c["forwarding"], branch_policy=c["branch_policy"],
                          watch_pcs=[hpc]).run()
        res = {"cycles": cpu.cycles, "retired": cpu.retired, "tx": bool(bus.radio_log),
               "first_radio_cycle": bus.radio_log[0][0] if bus.radio_log else None,
               "handler_start_cycle": cpu.watch_hit.get(hpc), "stats": cpu.stats(),
               "packet": [w for _, w in bus.radio_log]}
        self._cache[key] = res
        return res

    # ------------------------------------------------------------ simulations
    def simulate(self, mode, stream):
        if mode == "event":
            return self._sim_event(stream)
        return self._sim_polling(mode, stream)

    def _sim_event(self, st):
        cfg = self.cfg
        t1 = Tier1(cfg["thresholds"]["temp_c"])
        t2 = Tier2(cfg["thresholds"]["smoke"], cfg["tier2"]["persistence"], cfg["tier2"]["rearm_holdoff_s"])
        f = cfg["cpu"]["clock_hz"]
        events, cycles, tx = [], 0, 0
        for i in range(len(st)):
            t = i * st.dt
            if t2.update(t, t1.check(st.temp[i]), st.smoke[i]):
                r = self.run_core("event", st.temp[i], st.smoke[i])
                events.append(self._event(t, st.fire[i], r, f))
                cycles += r["cycles"]
                tx += r["tx"]
                t2.acknowledge(t)
        return self._activity("event", st, events, cycles, tx)

    def _sim_polling(self, mode, st):
        cfg = self.cfg
        f = cfg["cpu"]["clock_hz"]
        step = max(1, int(round(cfg["poll"]["period_s"] / st.dt)))
        holdoff = cfg["tier2"]["rearm_holdoff_s"]      # same alert re-send interval as event-driven
        quiet_until = -1.0
        events, cycles, tx = [], 0, 0
        for i in range(0, len(st), step):
            t = i * st.dt
            if t < quiet_until:
                r = self.run_core(mode, 0, 0)         # holdoff check: costs a normal no-alert poll
            else:
                r = self.run_core(mode, st.temp[i], st.smoke[i])
                if r["tx"]:
                    quiet_until = t + holdoff
            events.append(self._event(t, st.fire[i], r, f))
            cycles += r["cycles"]
            tx += r["tx"]
        return self._activity(mode, st, events, cycles, tx)

    @staticmethod
    def _event(t, fire, r, f):
        return {"t": t, "fire": fire, "cycles": r["cycles"], "tx": r["tx"],
                "tx_time": t + r["first_radio_cycle"] / f if r["tx"] else None,
                "boot_cycles": r["handler_start_cycle"]}

    @staticmethod
    def _activity(mode, st, events, cycles, tx):
        return {"mode": mode, "scenario": st.scenario, "duration_s": len(st) * st.dt,
                "core_wakes": len(events), "core_cycles": cycles,
                "sensor_samples": len(events), "tx_count": tx, "events": events,
                "ignite_s": st.ignite_s}

    # ------------------------------------------------------------ results
    def summarize(self, act, cfg=None):
        cfg = cfg or self.cfg
        en = compute_energy(act, cfg)
        ev = act["events"]
        true_tx = [e for e in ev if e["tx"] and e["fire"]]
        T = act["duration_s"]
        avg_p = en["total_j"] / T
        out = {
            "mode": act["mode"], "scenario": act["scenario"],
            "energy_j": en["total_j"], "avg_power_uw": avg_p * 1e6,
            "core_wakeups": act["core_wakes"],
            "idle_wakeups": sum(1 for e in ev if not e["fire"]),     # woke while no fire burning
            "transmissions": act["tx_count"],
            "false_transmissions": sum(1 for e in ev if e["tx"] and not e["fire"]),
            "missed_fire": None, "latency_s": None,
            "core_cycles": act["core_cycles"],
            "avg_cycles_per_wake": act["core_cycles"] / act["core_wakes"] if act["core_wakes"] else 0,
        }
        if act["ignite_s"] is not None:
            out["missed_fire"] = len(true_tx) == 0
            out["latency_s"] = (true_tx[0]["tx_time"] - act["ignite_s"]) if true_tx else None
        out.update({k: v for k, v in en.items()})
        return out
