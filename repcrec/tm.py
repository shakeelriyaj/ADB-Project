"""Transaction Manager (proposal §4.1).

Owns the logical clock, the transaction table, the ten Data Managers, the
wait queue, and the global per-variable commit log. Reads, writes and commit
validation are filled in by Phases 5-7; waiting/retry by Phase 8.

Output conventions:
  * Required output (reads, writes, commits/aborts, waits, dumps) goes to `out`.
  * Diagnostics about invalid scripts (unknown transaction, duplicate begin,
    op on a finished transaction) go to `err` and are otherwise ignored.
"""
import sys
from typing import Dict, List, Optional, TextIO, Tuple

from repcrec import output, placement
from repcrec.dm import DataManager, Version
from repcrec.parser import Command, Kind
from repcrec.transaction import Status, Transaction


class TransactionManager:
    def __init__(self, out: TextIO, err: TextIO = sys.stderr):
        self.out = out
        self.err = err
        self.time = 0
        self.sites: Dict[int, DataManager] = {s: DataManager(s) for s in placement.ALL_SITES}
        self.transactions: Dict[str, Transaction] = {}
        self.wait_queue: List[str] = []  # tids, FIFO
        # var -> [(commit_time, tid)] for every committed write, across all
        # sites. Used for first-committer-wins: a site that was down may have
        # missed commits, so no single site's versions are complete.
        self.commit_log: Dict[int, List[Tuple[int, str]]] = {v: [] for v in placement.ALL_VARIABLES}

    # ------------------------------------------------------------ plumbing

    def _emit(self, msg: str) -> None:
        print(msg, file=self.out)

    def _warn(self, msg: str) -> None:
        print(f"[t={self.time}] warning: {msg}", file=self.err)

    def advance(self, tick: int) -> None:
        """Called for lines with no command (blank/comment) so time still moves."""
        self.time = tick

    def process(self, cmd: Command, tick: int) -> None:
        """Execute one command at logical time `tick`."""
        self.time = tick
        handler = {
            Kind.BEGIN: self._begin,
            Kind.READ: self._read,
            Kind.WRITE: self._write,
            Kind.END: self._end,
            Kind.FAIL: self._fail,
            Kind.RECOVER: self._recover,
            Kind.DUMP: self._dump,
            Kind.QUERYSTATE: self._querystate,
        }[cmd.kind]
        handler(cmd)

    def _live_txn(self, cmd: Command) -> Optional[Transaction]:
        """Look up the transaction a command refers to; warn if it can't run."""
        txn = self.transactions.get(cmd.tid)
        if txn is None:
            self._warn(f"{cmd.tid} has not begun; ignoring {cmd.kind.value}")
            return None
        if not txn.is_live:
            self._warn(f"{cmd.tid} already {txn.status.value}; ignoring {cmd.kind.value}")
            return None
        if txn.status is Status.WAITING:
            # FAQ: scripts never issue a new op for a blocked transaction.
            self._warn(f"{cmd.tid} is waiting; ignoring {cmd.kind.value}")
            return None
        return txn

    # ------------------------------------------------------------ commands

    def _begin(self, cmd: Command) -> None:
        if cmd.tid in self.transactions:
            self._warn(f"{cmd.tid} already exists; ignoring begin")
            return
        self.transactions[cmd.tid] = Transaction(cmd.tid, self.time)

    def _read(self, cmd: Command) -> None:
        """R(T, x): snapshot read as of T's begin time (proposal §4.3)."""
        txn = self._live_txn(cmd)
        if txn is None:
            return
        var = cmd.var

        # 1. Read-your-own-writes.
        if var in txn.write_buffer:
            self._emit(output.read(txn.tid, var, txn.write_buffer[var]))
            return

        # 2/3. Read T's snapshot from any valid up site, else wait or abort.
        ver, down = self._snapshot(var, txn.begin_time)
        if ver is not None:
            txn.record_read(var, ver.writer, ver.commit_time)
            self._emit(output.read(txn.tid, var, ver.value))
        elif down:
            self._block(txn, cmd, down)
        else:
            self._abort(txn, output.reason_no_snapshot(txn.tid, var))

    def _snapshot(self, var: int, begin_time: int) -> Tuple[Optional[Version], List[int]]:
        """T's snapshot of x`var` from an up site, plus the down sites that hold it.

        Any valid up site gives the same version (see DataManager.snapshot_version).
        """
        down = []
        for s in placement.sites_for(var):
            dm = self.sites[s]
            ver = dm.snapshot_version(var, begin_time)
            if ver is None:
                continue
            if dm.is_up:
                return ver, []
            down.append(s)
        return None, down

    def _block(self, txn: Transaction, cmd: Command, sites: List[int]) -> None:
        """Park `cmd` until one of `sites` recovers (retried in Phase 8)."""
        txn.block(cmd)
        self.wait_queue.append(txn.tid)
        op = "read" if cmd.kind is Kind.READ else "write"
        self._emit(output.wait(txn.tid, sites, op, cmd.var))

    def _abort(self, txn: Transaction, reason: str) -> None:
        txn.abort(reason)
        if txn.tid in self.wait_queue:
            self.wait_queue.remove(txn.tid)
        self._emit(output.abort(txn.tid, reason))

    def _write(self, cmd: Command) -> None:
        if self._live_txn(cmd) is None:
            return
        self._warn("W not implemented yet (Phase 6)")

    def _end(self, cmd: Command) -> None:
        if self._live_txn(cmd) is None:
            return
        self._warn("end not implemented yet (Phase 7)")

    def _fail(self, cmd: Command) -> None:
        # Transactions that wrote to this site are aborted lazily at end()
        # (Available Copies rule; Test 4 allows either).
        self.sites[cmd.site].fail(self.time)

    def _recover(self, cmd: Command) -> None:
        self.sites[cmd.site].recover(self.time)
        self._retry_waiting()

    def _retry_waiting(self) -> None:
        """Re-attempt blocked operations in FIFO order (Phase 8)."""

    def _dump(self, cmd: Command) -> None:
        for s in placement.ALL_SITES:
            self._emit(self.sites[s].dump_line())

    def _querystate(self, cmd: Command) -> None:
        for line in self.querystate_lines():
            self._emit(line)

    # ----------------------------------------------------------- debugging

    def querystate_lines(self) -> List[str]:
        lines = [f"=== querystate @ t={self.time} ==="]

        lines.append("Sites:")
        for s, dm in self.sites.items():
            status = "up" if dm.is_up else "DOWN"
            hist = ", ".join(
                f"[{f},{'' if r is None else r})" for f, r in dm.down_intervals
            ) or "none"
            lines.append(f"  site {s}: {status}; outages: {hist}")

        lines.append("Transactions:")
        if not self.transactions:
            lines.append("  (none)")
        for txn in self.transactions.values():
            parts = [f"{txn.tid}: {txn.status.value}", f"begin={txn.begin_time}"]
            if txn.commit_time is not None:
                parts.append(f"commit={txn.commit_time}")
            if txn.abort_reason:
                parts.append(f"reason={txn.abort_reason}")
            if txn.write_buffer:
                writes = ", ".join(
                    f"x{v}={val}->{sorted(txn.write_sites.get(v, ()))}"
                    for v, val in sorted(txn.write_buffer.items())
                )
                parts.append(f"writes[{writes}]")
            if txn.read_set:
                reads = ", ".join(
                    f"x{v}@{w}:{t}" for v, (w, t) in sorted(txn.read_set.items())
                )
                parts.append(f"reads[{reads}]")
            if txn.pending is not None:
                parts.append(f"pending={txn.pending.kind.value}")
            lines.append("  " + "; ".join(parts))

        lines.append(f"Wait queue: {self.wait_queue or '(empty)'}")

        lines.append("Data (* = replicated copy not readable since recovery):")
        for s, dm in self.sites.items():
            vals = ", ".join(
                f"x{v}: {dm.latest_version(v).value}{'' if dm.readable[v] else '*'}"
                for v in sorted(dm.versions)
            )
            lines.append(f"  site {s} - {vals}")
        return lines
