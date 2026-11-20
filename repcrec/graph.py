"""Serialization graph and SSI dangerous-structure detection (proposal §4.7).

Nodes are committed transactions plus the one currently trying to commit.
Edge kinds:
  ww  C -> T  both wrote x; C's version comes first
  wr  C -> T  T read the version of x that C wrote
  rw  A -> B  A read a version of x that B overwrote (anti-dependency)

Only committed transactions are nodes (Test 18). Committed transactions are
never removed (Test 22 needs T1 after it no longer overlaps T3).
"""
from typing import Dict, Iterable, List, Set, Tuple

WW, WR, RW = "ww", "wr", "rw"

Edge = Tuple[str, str, str]  # (from tid, to tid, kind)


class SerializationGraph:
    def __init__(self) -> None:
        self._out: Dict[str, Set[Tuple[str, str]]] = {}  # u -> {(v, kind)}

    def add_edges(self, edges: Iterable[Edge]) -> None:
        for u, v, kind in edges:
            self._out.setdefault(u, set()).add((v, kind))

    def edges(self) -> List[Edge]:
        return sorted((u, v, k) for u, outs in self._out.items() for v, k in outs)

    def has_dangerous_cycle(self, tid: str, new_edges: Iterable[Edge]) -> bool:
        """Would adding `new_edges` (all touching `tid`) close a cycle through
        `tid` that contains two consecutive rw edges?

        The graph itself is not modified. Enumerates simple cycles through
        `tid` with a DFS, which is fine for test-script-sized graphs.
        """
        adj: Dict[str, Set[Tuple[str, str]]] = {u: set(o) for u, o in self._out.items()}
        for u, v, kind in new_edges:
            adj.setdefault(u, set()).add((v, kind))

        def dfs(node: str, kinds: List[str], visited: Set[str]) -> bool:
            for nxt, kind in sorted(adj.get(node, ())):
                if nxt == tid:
                    if _has_consecutive_rw(kinds + [kind]):
                        return True
                elif nxt not in visited:
                    visited.add(nxt)
                    if dfs(nxt, kinds + [kind], visited):
                        return True
                    visited.remove(nxt)
            return False

        return dfs(tid, [], {tid})


def _has_consecutive_rw(cycle_kinds: List[str]) -> bool:
    """True if two adjacent edges of the cycle are both rw (wrapping around)."""
    n = len(cycle_kinds)
    if n < 2:
        return False
    return any(cycle_kinds[i] == RW and cycle_kinds[(i + 1) % n] == RW for i in range(n))
