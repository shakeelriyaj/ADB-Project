"""Transaction Manager (proposal §4.1).

Owns the logical clock, the transaction table, the ten Data Managers, the
wait queue, and the global per-variable commit log. Reads, writes and commit
validation and waiting/retry are implemented below.

Output conventions:
  * Required output (reads, writes, commits/aborts, waits, dumps) goes to `out`.
  * Diagnostics about invalid scripts (unknown transaction, duplicate begin,
    op on a finished transaction) go to `err` and are otherwise ignored.
"""
import sys
from typing import Dict, List, Optional, TextIO, Tuple

from repcrec import output, placement
from repcrec.dm import DataManager, Version
from repcrec.graph import RW, WR, WW, Edge, SerializationGraph
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
        self.graph = SerializationGraph()

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
        """Park `cmd` until one of `sites` recovers (see _retry_waiting)."""
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
        """W(T, x, v): buffer the write and note which sites it will go to (§4.4).

        The target sites are the ones holding x that are up *now*. At commit
        the value goes to exactly these sites, never to a site that recovers
        later (Test 3.5). If one of them fails before end(T), the Available
        Copies rule aborts T. If no site holding x is up, T waits.
        """
        txn = self._live_txn(cmd)
        if txn is None:
            return
        holders = placement.sites_for(cmd.var)
        up = [s for s in holders if self.sites[s].is_up]
        if not up:
            self._block(txn, cmd, holders)
            return
        txn.record_write(cmd.var, cmd.value, up, self.time)
        self._emit(output.write(txn.tid, cmd.var, cmd.value, up))

    def _end(self, cmd: Command) -> None:
        """end(T): validate, then commit or abort (proposal §4.5).

        Checks run in a fixed order and only the first failure is reported:
        Available Copies, then first committer wins, then SSI.
        """
        txn = self._live_txn(cmd)
        if txn is None:
            return
        reason = (self._available_copies_violation(txn)
                  or self._first_committer_wins_violation(txn))
        if reason is None:
            edges = self._edges_with_committed(txn)
            if self.graph.has_dangerous_cycle(txn.tid, edges):
                reason = output.reason_ssi()
        if reason is not None:
            self._abort(txn, reason)
            return
        self._commit(txn, edges)

    def _available_copies_violation(self, txn: Transaction) -> Optional[str]:
        """A site T wrote to failed after T's first write there (§4.5.1)."""
        for site in sorted(txn.first_write_at_site):
            if self.sites[site].failed_between(txn.first_write_at_site[site], self.time):
                return output.reason_available_copies(txn.tid, site)
        return None

    def _first_committer_wins_violation(self, txn: Transaction) -> Optional[str]:
        """Another transaction committed a var T wrote after T began (§4.5.2)."""
        for var in sorted(txn.write_set):
            later = [(t, w) for t, w in self.commit_log[var] if t > txn.begin_time]
            if later:
                return output.reason_first_committer_wins(txn.tid, min(later)[1], var)
        return None

    def _edges_with_committed(self, txn: Transaction) -> List[Edge]:
        """Serialization-graph edges between T and every committed transaction.

        Edges among committed transactions were added when the later of the
        pair committed, so only edges touching T are new.
        """
        edges: List[Edge] = []
        for c in self.transactions.values():
            if c.status is not Status.COMMITTED:
                continue
            for var in txn.write_set & c.write_set:
                edges.append((c.tid, txn.tid, WW))       # c's version precedes T's
            for var, (writer, ver_time) in txn.read_set.items():
                if writer == c.tid:
                    edges.append((c.tid, txn.tid, WR))   # T read c's version
                elif var in c.write_set and c.commit_time > ver_time:
                    edges.append((txn.tid, c.tid, RW))   # c overwrote what T read
            for var in c.read_set:
                if var in txn.write_set:
                    edges.append((c.tid, txn.tid, RW))   # T overwrites what c read
        return edges

    def _commit(self, txn: Transaction, edges: List[Edge]) -> None:
        """Apply T's writes to the sites recorded at write time (Test 3.5).

        The Available Copies check guarantees none of them failed since, so
        they are all up.
        """
        for var, value in sorted(txn.write_buffer.items()):
            for s in sorted(txn.write_sites[var]):
                self.sites[s].apply_commit(var, value, self.time, txn.tid)
            self.commit_log[var].append((self.time, txn.tid))
        txn.status = Status.COMMITTED
        txn.commit_time = self.time
        self.graph.add_edges(edges)
        self._emit(output.commit(txn.tid))

    def _fail(self, cmd: Command) -> None:
        # Transactions that wrote to this site are aborted lazily at end()
        # (Available Copies rule; Test 4 allows either).
        self.sites[cmd.site].fail(self.time)

    def _recover(self, cmd: Command) -> None:
        self.sites[cmd.site].recover(self.time)
        self._retry_waiting()

    def _retry_waiting(self) -> None:
        """After a recovery, resume blocked operations that can now run (§4.6).

        Queue order is FIFO. An op that still can't run stays queued without
        printing its wait line again. A resumed read still uses T's original
        snapshot (begin_time), and a resumed write targets the sites up now.
        """
        for tid in list(self.wait_queue):
            txn = self.transactions[tid]
            cmd = txn.pending
            if not self._can_proceed(txn, cmd):
                continue
            self.wait_queue.remove(tid)
            txn.unblock()
            {Kind.READ: self._read, Kind.WRITE: self._write}[cmd.kind](cmd)

    def _can_proceed(self, txn: Transaction, cmd: Command) -> bool:
        if cmd.kind is Kind.READ:
            ver, _ = self._snapshot(cmd.var, txn.begin_time)
            return ver is not None
        return any(self.sites[s].is_up for s in placement.sites_for(cmd.var))

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
        edges = ", ".join(f"{u} -{k}-> {v}" for u, v, k in self.graph.edges())
        lines.append(f"Serialization graph: {edges or '(no edges)'}")

        lines.append("Data (* = replicated copy not readable since recovery):")
        for s, dm in self.sites.items():
            vals = ", ".join(
                f"x{v}: {dm.latest_version(v).value}{'' if dm.readable[v] else '*'}"
                for v in sorted(dm.versions)
            )
            lines.append(f"  site {s} - {vals}")
        return lines
