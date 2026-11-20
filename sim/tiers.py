"""
tiers.py - Behavioural models of the always-on hardware (Step 8).

Tier 1 (Sentry)     : analog comparator, flags temperature above a threshold.
Tier 2 (Controller) : digital logic. WAKE_UP is asserted only if
                         temperature flag AND smoke >= threshold
                      hold for `persistence` consecutive samples. After an alert it
                      is disarmed for `rearm_holdoff_s` (the core's SLEEP write acts as ack).
"""


class Tier1:
    def __init__(self, temp_threshold):
        self.threshold = temp_threshold

    def check(self, temp):
        return temp > self.threshold


class Tier2:
    def __init__(self, smoke_threshold, persistence, rearm_holdoff_s):
        self.smoke_threshold = smoke_threshold
        self.persistence = persistence
        self.holdoff = rearm_holdoff_s
        self.count = 0
        self.disarmed_until = -1.0

    def update(self, t, tier1_flag, smoke):
        """Called every sample; returns True when WAKE_UP is asserted."""
        if t < self.disarmed_until:
            self.count = 0
            return False
        if tier1_flag and smoke >= self.smoke_threshold:
            self.count += 1
        else:
            self.count = 0
        if self.count >= self.persistence:
            self.count = 0
            return True
        return False

    def acknowledge(self, t):
        self.disarmed_until = t + self.holdoff
