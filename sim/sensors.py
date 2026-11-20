"""
sensors.py - Synthetic, labelled temperature + smoke streams (Step 8).

Scenarios
  normal   : mild diurnal temperature (15..35 C), low smoke
  heatwave : hot day (28..56 C) with sun-baked spells above 60 C, and hazy air
             (slowly wandering smoke index) - a lot of temperature-only "events"
  wildfire : normal day until ignition; then temperature and smoke ramp up
All streams contain single-sample glitches (EMI/ADC spikes) to test the persistence filter.
Ground truth (`fire[i]`) lets us count false wake-ups / missed fires exactly.
"""
import math
import random
from dataclasses import dataclass, field


@dataclass
class Stream:
    scenario: str
    dt: float
    temp: list = field(default_factory=list)    # degrees C (int)
    smoke: list = field(default_factory=list)   # index 0..100 (int)
    fire: list = field(default_factory=list)    # ground truth: is a fire burning?
    ignite_s: float = None

    def __len__(self):
        return len(self.temp)


def _bump(t, centre, width, amp):
    """Smooth raised-cosine bump of total width `width` seconds."""
    x = (t - centre) / (width / 2)
    return amp * 0.5 * (1 + math.cos(math.pi * x)) if abs(x) < 1 else 0.0


def generate(scenario, duration_s=86400, dt=1.0, seed=1, ignite_s=None, glitch_prob=1e-3):
    rng = random.Random(f"{scenario}-{seed}")
    n = int(duration_s / dt)
    if scenario == "wildfire" and ignite_s is None:
        ignite_s = rng.uniform(10 * 3600, 18 * 3600)
    st = Stream(scenario, dt, ignite_s=ignite_s if scenario == "wildfire" else None)

    mean, amp = {"normal": (25, 10), "heatwave": (42, 14), "wildfire": (25, 10)}[scenario]
    haze = 0.0
    spells = [(13.5 * 3600, 900, 13), (15.2 * 3600, 1200, 12)] if scenario == "heatwave" else []

    for i in range(n):
        t = i * dt
        base = mean + amp * math.sin(2 * math.pi * (t - 9 * 3600) / 86400)   # peaks 15:00
        temp = base + rng.gauss(0, 0.4)
        smoke = 4 + rng.gauss(0, 1.0)

        if scenario == "heatwave":
            temp += sum(_bump(t, c, w, a) for c, w, a in spells)
            haze = 0.98 * haze + rng.gauss(0, 1.5)           # AR(1) haze episodes
            smoke += 6 + haze

        fire = False
        if scenario == "wildfire" and t >= st.ignite_s:
            fire = True
            x = t - st.ignite_s
            temp = base + (180 - base) * (1 - math.exp(-x / 30)) + rng.gauss(0, 2.0)
            smoke = 4 + 85 * (1 - math.exp(-x / 25)) + rng.gauss(0, 2.0)

        if rng.random() < glitch_prob:                       # single-sample glitch
            if rng.random() < 0.5:
                temp += 25
            else:
                smoke += 40

        st.temp.append(int(round(temp)))
        st.smoke.append(int(max(0, min(100, round(smoke)))))
        st.fire.append(fire)
    return st
