"""Data Manager: one per site (proposal §4.1, §4.6).

Each DM stores, for every variable it holds, the list of committed versions
in commit order. Committed data survives failure (and is shown by dump());
only the volatile per-variable "readable" flags are reset.

The DM also records its own failure/recovery intervals so the TM can ask
"was this site up continuously from t1 to t2?" (read rule §4.3.3) and
"did this site fail between t1 and t2?" (Available Copies rule §4.5.1).

Time convention: every input line is a distinct tick, so no two events share
a timestamp. Initial values are committed at time 0 by the pseudo-transaction
INITIAL_TID.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from repcrec import placement

INITIAL_TID = "T0"


@dataclass(frozen=True)
class Version:
    value: int
    commit_time: int
    writer: str  # transaction id that committed this version


class SiteDownError(RuntimeError):
    pass


class DataManager:
    def __init__(self, site_id: int):
        self.site_id = site_id
        self.is_up = True
        self.versions: Dict[int, List[Version]] = {
            v: [Version(placement.initial_value(v), 0, INITIAL_TID)]
            for v in placement.variables_at(site_id)
        }
        # Volatile: whether a replicated var has been written since the last
        # recovery. Informational only (querystate); the TM's read rule uses
        # failure history instead, because a transaction that began before a
        # failure may still read the old version after recovery (Test 25).
        self.readable: Dict[int, bool] = {v: True for v in self.versions}
        # Down intervals as [fail_time, recover_time); recover_time is None
        # while the site is still down.
        self.down_intervals: List[Tuple[int, Optional[int]]] = []

    # ------------------------------------------------------------------ data

    def holds(self, var: int) -> bool:
        return var in self.versions

    def latest_version(self, var: int) -> Version:
        return self.versions[var][-1]

    def version_as_of(self, var: int, t: int) -> Version:
        """Latest version of `var` committed at or before time `t`.

        Always exists because the initial version is committed at time 0.
        """
        for ver in reversed(self.versions[var]):
            if ver.commit_time <= t:
                return ver
        raise AssertionError(f"no version of x{var} at site {self.site_id} as of {t}")

    def snapshot_version(self, var: int, t: int) -> Optional[Version]:
        """The version a transaction that began at `t` may read here, or None.

        Unreplicated: always valid. It is the only copy, so nothing can have
        been committed to it while the site was down.

        Replicated: valid only if the site was up continuously from the commit
        of its latest version at or before t until t. A failure in that window
        means the site may have missed later commits (§4.3.3). This also
        covers §4.3.4, since a site that recovered before t, with no new
        commit since, fails the check. A site that failed *after* t still
        qualifies once it is back up (Test 25).
        """
        ver = self.version_as_of(var, t)
        if placement.is_replicated(var) and not self.was_up_throughout(ver.commit_time, t):
            return None
        return ver

    def apply_commit(self, var: int, value: int, commit_time: int, writer: str) -> None:
        if not self.is_up:
            raise SiteDownError(f"site {self.site_id} is down; cannot apply write to x{var}")
        if not self.holds(var):
            raise KeyError(f"site {self.site_id} does not hold x{var}")
        assert commit_time > self.versions[var][-1].commit_time, "commits must be in time order"
        self.versions[var].append(Version(value, commit_time, writer))
        self.readable[var] = True

    # ------------------------------------------------------ failure/recovery

    def fail(self, t: int) -> None:
        if not self.is_up:
            return  # already down; nothing changes
        self.is_up = False
        self.down_intervals.append((t, None))

    def recover(self, t: int) -> None:
        if self.is_up:
            return
        self.is_up = True
        fail_time, _ = self.down_intervals[-1]
        self.down_intervals[-1] = (fail_time, t)
        for var in self.readable:
            # Unreplicated vars have no other copy, so they are current as-is.
            self.readable[var] = not placement.is_replicated(var)

    def was_up_throughout(self, start: int, end: int) -> bool:
        """True if the site was up at every moment in [start, end]."""
        for fail_time, recover_time in self.down_intervals:
            if fail_time <= end and (recover_time is None or recover_time > start):
                return False
        return True

    def failed_between(self, start: int, end: int) -> bool:
        """True if the site had a failure event at some time in (start, end]."""
        return any(start < fail_time <= end for fail_time, _ in self.down_intervals)

    # ---------------------------------------------------------------- output

    def dump_line(self) -> str:
        """Committed values in ascending variable order, shown even if the site is down."""
        body = ", ".join(f"x{v}: {self.versions[v][-1].value}" for v in sorted(self.versions))
        return f"site {self.site_id} - {body}"
