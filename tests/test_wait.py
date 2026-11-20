"""Phase 8: blocked operations resume on recovery (proposal §4.6)."""
from repcrec.transaction import Status
from tests.helpers import fail_all_but, run_script


def test_unreplicated_read_resumes_on_recover():
    tm, out, _ = run_script("begin(T1)\nfail(4)\nR(T1,x3)\nrecover(4)\nend(T1)\n")
    assert out.splitlines() == [
        "T1 waits for site 4 to read x3",
        "T1 reads x3: 30",
        "T1 commits",
    ]
    assert tm.wait_queue == []


def test_unrelated_recovery_does_not_resume_or_reprint():
    tm, out, _ = run_script("begin(T1)\nfail(4)\nfail(5)\nR(T1,x3)\nrecover(5)\n")
    assert out.splitlines() == ["T1 waits for site 4 to read x3"]
    assert tm.transactions["T1"].status is Status.WAITING
    assert tm.wait_queue == ["T1"]


def test_replicated_read_waits_for_a_qualifying_site():
    # Sites 1-9 failed before T1 began, so recovering one of them doesn't help;
    # only site 10 (failed after T1 began) still holds T1's snapshot.
    script = fail_all_but(10) + "begin(T1)\nfail(10)\nR(T1,x2)\nrecover(3)\nrecover(10)\n"
    _, out, _ = run_script(script)
    assert out.splitlines() == [
        "T1 waits for site 10 to read x2",
        "T1 reads x2: 20",
    ]


def test_resumed_read_uses_original_snapshot():
    script = (
        "begin(T1)\nbegin(T2)\nW(T2,x2,99)\nend(T2)\n"
        + fail_all_but()
        + "R(T1,x2)\nrecover(3)\n"
    )
    _, out, _ = run_script(script)
    assert out.splitlines()[-2:] == [
        "T1 waits for sites 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 to read x2",
        "T1 reads x2: 20",
    ]


def test_write_resumes_and_commits_to_sites_up_at_resume():
    tm, out, _ = run_script("begin(T1)\nfail(4)\nW(T1,x3,33)\nrecover(4)\nend(T1)\n")
    assert out.splitlines() == [
        "T1 waits for site 4 to write x3",
        "T1 writes x3: 33 to site 4",
        "T1 commits",
    ]
    t1 = tm.transactions["T1"]
    assert t1.first_write_at_site == {4: 4}       # time of the resumed write
    assert tm.sites[4].latest_version(3).value == 33


def test_replicated_write_resumes_on_first_recovered_site():
    script = "begin(T1)\n" + fail_all_but() + "W(T1,x2,5)\nrecover(7)\nrecover(8)\nend(T1)\n"
    tm, out, _ = run_script(script)
    assert out.splitlines()[-2:] == ["T1 writes x2: 5 to site 7", "T1 commits"]
    assert tm.sites[7].latest_version(2).value == 5
    assert tm.sites[8].latest_version(2).value == 20   # recovered after the write


def test_waiting_transactions_resume_in_fifo_order():
    script = (
        "begin(T1)\nbegin(T2)\nbegin(T3)\nfail(4)\n"
        "R(T2,x3)\nW(T1,x13,1)\nR(T3,x13)\nrecover(4)\n"
    )
    _, out, _ = run_script(script)
    assert out.splitlines()[3:] == [
        "T2 reads x3: 30",
        "T1 writes x13: 1 to site 4",
        "T3 reads x13: 130",
    ]


def test_resumed_transaction_accepts_new_ops():
    _, out, err = run_script("begin(T1)\nfail(4)\nR(T1,x3)\nrecover(4)\nR(T1,x2)\n")
    assert out.splitlines()[-1] == "T1 reads x2: 20"
    assert err == ""


def test_available_copies_after_resumed_write():
    # The resumed write's site fails before end: Available Copies abort.
    _, out, _ = run_script(
        "begin(T1)\nfail(4)\nW(T1,x3,33)\nrecover(4)\nfail(4)\nrecover(4)\nend(T1)\n")
    assert out.splitlines()[-1] == "T1 aborts: available copies (site 4 failed after T1 wrote to it)"


def test_querystate_shows_pending_op():
    _, out, _ = run_script("begin(T1)\nfail(4)\nR(T1,x3)\nquerystate()\n")
    assert "T1: waiting; begin=1; pending=R" in out
    assert "Wait queue: ['T1']" in out
