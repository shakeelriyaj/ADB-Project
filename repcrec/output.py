"""Every line of required output, in one place.

The format is fixed by tests/expected/*.txt; see "Output format" in PLAN.md.
"""
from typing import Iterable


def _site_list(sites: Iterable[int]) -> str:
    sites = sorted(sites)
    label = "site" if len(sites) == 1 else "sites"
    return f"{label} {', '.join(map(str, sites))}"


def read(tid: str, var: int, value: int) -> str:
    return f"{tid} reads x{var}: {value}"


def write(tid: str, var: int, value: int, sites: Iterable[int]) -> str:
    return f"{tid} writes x{var}: {value} to {_site_list(sites)}"


def wait(tid: str, sites: Iterable[int], op: str, var: int) -> str:
    """op is "read" or "write"."""
    return f"{tid} waits for {_site_list(sites)} to {op} x{var}"


def commit(tid: str) -> str:
    return f"{tid} commits"


def abort(tid: str, reason: str) -> str:
    return f"{tid} aborts: {reason}"


# ------------------------------------------------------------ abort reasons

def reason_available_copies(tid: str, site: int) -> str:
    return f"available copies (site {site} failed after {tid} wrote to it)"


def reason_first_committer_wins(tid: str, winner: str, var: int) -> str:
    return f"first committer wins ({winner} committed x{var} after {tid} began)"


def reason_ssi() -> str:
    return "SSI (commit would close a cycle with two consecutive rw edges)"


def reason_no_snapshot(tid: str, var: int) -> str:
    return (f"no valid snapshot of x{var} "
            f"(no site up continuously from its last commit until {tid} began)")
