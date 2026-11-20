"""Phase 7: commit validation and applying writes (proposal §4.5)."""
from repcrec import placement
from repcrec.graph import RW, WR
from repcrec.transaction import Status
from tests.helpers import run_script

ALL = "sites 1, 2, 3, 4, 5, 6, 7, 8, 9, 10"


def last_line(out: str) -> str:
    return out.splitlines()[-1]


# ----------------------------------------------------------------- commit

def test_commit_applies_writes_with_commit_time():
    tm, out, _ = run_script("begin(T1)\nW(T1,x2,5)\nW(T1,x1,7)\nend(T1)\n")
    assert last_line(out) == "T1 commits"
    t1 = tm.transactions["T1"]
    assert t1.status is Status.COMMITTED and t1.commit_time == 4
    for s in placement.ALL_SITES:
        v = tm.sites[s].latest_version(2)
        assert (v.value, v.commit_time, v.writer) == (5, 4, "T1")
    assert tm.sites[2].latest_version(1).value == 7
    assert tm.commit_log[2] == [(4, "T1")]


def test_read_only_and_empty_transactions_commit():
    _, out, _ = run_script("begin(T1)\nR(T1,x2)\nend(T1)\nbegin(T2)\nend(T2)\n")
    assert out.splitlines()[1:] == ["T1 commits", "T2 commits"]


def test_commit_does_not_write_to_site_recovered_after_write():
    # Test 3.5: no retroactive writes.
    tm, _, _ = run_script("begin(T1)\nfail(2)\nW(T1,x4,91)\nrecover(2)\nend(T1)\n")
    assert tm.sites[2].latest_version(4).value == 40
    assert tm.sites[1].latest_version(4).value == 91
    assert not tm.sites[2].readable[4]


def test_commit_makes_recovered_replica_readable():
    script = "fail(3)\nrecover(3)\nbegin(T1)\nW(T1,x2,9)\nend(T1)\nbegin(T2)\n"
    script += "".join(f"fail({s})\n" for s in placement.ALL_SITES if s != 3)
    script += "R(T2,x2)\n"
    _, out, _ = run_script(script)
    assert last_line(out) == "T2 reads x2: 9"


# ------------------------------------------------------- available copies

def test_available_copies_abort():
    tm, out, _ = run_script("begin(T1)\nW(T1,x6,66)\nfail(2)\nrecover(2)\nend(T1)\n")
    assert last_line(out) == "T1 aborts: available copies (site 2 failed after T1 wrote to it)"
    assert tm.sites[1].latest_version(6).value == 60          # nothing applied
    assert tm.commit_log[6] == []


def test_failure_before_write_does_not_abort():
    _, out, _ = run_script("begin(T1)\nfail(2)\nrecover(2)\nW(T1,x6,66)\nend(T1)\n")
    assert last_line(out) == "T1 commits"


def test_failure_of_unwritten_site_does_not_abort():
    _, out, _ = run_script("begin(T1)\nW(T1,x3,1)\nfail(2)\nend(T1)\n")   # x3 is at site 4
    assert last_line(out) == "T1 commits"


def test_failure_of_read_site_does_not_abort():
    # Proposal §4.3.5 (still an open TA question; see PLAN.md).
    _, out, _ = run_script("begin(T1)\nR(T1,x3)\nfail(4)\nend(T1)\n")
    assert last_line(out) == "T1 commits"


def test_available_copies_reports_lowest_failed_site():
    _, out, _ = run_script("begin(T1)\nW(T1,x2,1)\nfail(7)\nfail(3)\nend(T1)\n")
    assert last_line(out) == "T1 aborts: available copies (site 3 failed after T1 wrote to it)"


# --------------------------------------------------- first committer wins

def test_first_committer_wins():
    _, out, _ = run_script(
        "begin(T1)\nbegin(T2)\nW(T1,x2,1)\nW(T2,x2,2)\nend(T2)\nend(T1)\n")
    assert last_line(out) == "T1 aborts: first committer wins (T2 committed x2 after T1 began)"


def test_commit_before_begin_is_not_a_conflict():
    _, out, _ = run_script(
        "begin(T1)\nW(T1,x2,1)\nend(T1)\nbegin(T2)\nW(T2,x2,2)\nend(T2)\n")
    assert last_line(out) == "T2 commits"


def test_aborted_writer_does_not_trigger_fcw():
    _, out, _ = run_script(
        "begin(T1)\nbegin(T2)\nW(T1,x2,1)\nfail(1)\nend(T1)\nW(T2,x4,2)\nend(T2)\n")
    assert out.splitlines()[-1] == "T2 commits"


def test_available_copies_checked_before_fcw():
    _, out, _ = run_script(
        "begin(T1)\nbegin(T2)\nW(T1,x2,1)\nW(T2,x4,2)\nfail(5)\nrecover(5)\n"
        "W(T2,x2,9)\nend(T2)\nend(T1)\n")
    assert last_line(out).startswith("T1 aborts: available copies (site 5")


# -------------------------------------------------------------------- SSI

def test_write_skew_aborts():
    # Test 21.
    _, out, _ = run_script(
        "begin(T1)\nbegin(T2)\nR(T1,x2)\nR(T2,x4)\nW(T1,x4,30)\nW(T2,x2,90)\nend(T1)\nend(T2)\n")
    assert out.splitlines()[-2:] == [
        "T1 commits",
        "T2 aborts: SSI (commit would close a cycle with two consecutive rw edges)",
    ]


def test_edges_recorded_on_commit():
    tm, _, _ = run_script(
        "begin(T1)\nbegin(T2)\nW(T1,x2,80)\nW(T1,x4,50)\nR(T2,x4)\nend(T1)\n"
        "begin(T3)\nR(T3,x2)\nend(T2)\nend(T3)\n")
    assert [t.status for t in tm.transactions.values()] == [Status.COMMITTED] * 3
    assert tm.graph.edges() == [
        ("T1", "T3", WR),     # T3 began after T1 committed and read its x2
        ("T2", "T1", RW),     # T2 read x4 before T1's version
    ]


def test_reading_committed_writer_can_close_a_cycle():
    # Like Test 22, but T3 closes the cycle with a wr edge instead of ww:
    # T3 -rw-> T2 -rw-> T1 -wr-> T3.
    _, out, _ = run_script(
        "begin(T1)\nbegin(T2)\nW(T1,x2,80)\nW(T1,x4,50)\nR(T2,x4)\nend(T1)\n"
        "W(T2,x6,90)\nbegin(T3)\nR(T3,x6)\nR(T3,x2)\nend(T2)\nend(T3)\n")
    assert last_line(out) == "T3 aborts: SSI (commit would close a cycle with two consecutive rw edges)"


def test_aborted_transaction_adds_no_edges():
    tm, _, _ = run_script(
        "begin(T1)\nbegin(T2)\nR(T1,x2)\nR(T2,x4)\nW(T1,x4,30)\nW(T2,x2,90)\nend(T1)\nend(T2)\n")
    assert tm.graph.edges() == []        # T1 committed first with nothing to link to


def test_querystate_shows_graph():
    _, out, _ = run_script(
        "begin(T1)\nbegin(T2)\nR(T2,x2)\nW(T1,x2,5)\nend(T1)\nend(T2)\nquerystate()\n")
    assert "Serialization graph: T2 -rw-> T1" in out
