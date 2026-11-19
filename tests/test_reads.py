"""Phase 5: read rules (proposal §4.3).

Writes and commits aren't wired up yet, so tests that need committed versions
install them directly on the DataManagers.
"""
from repcrec import placement
from repcrec.parser import parse_line
from repcrec.transaction import Status
from tests.helpers import fail_all_but, run_script, step


# ------------------------------------------------------------ basic reads

def test_read_initial_values():
    tm, out, err = run_script("begin(T1)\nR(T1,x3)\nR(T1,x2)\nR(T1,x20)\n")
    assert out == "T1 reads x3: 30\nT1 reads x2: 20\nT1 reads x20: 200\n"
    assert err == ""
    assert tm.transactions["T1"].read_set == {3: ("T0", 0), 2: ("T0", 0), 20: ("T0", 0)}


def test_read_own_write_is_not_recorded_as_a_read():
    tm, _, _ = run_script("begin(T1)\n")
    tm.transactions["T1"].record_write(4, 99, placement.sites_for(4), tm.time)
    assert step(tm, "R(T1,x4)") == "T1 reads x4: 99\n"
    assert tm.transactions["T1"].read_set == {}


def test_snapshot_ignores_commits_after_begin():
    tm, _, _ = run_script("begin(T1)\n")
    for s in placement.ALL_SITES:
        tm.sites[s].apply_commit(2, 22, 2, "T9")
    tm.sites[4].apply_commit(3, 33, 2, "T9")
    tm.time = 2
    assert step(tm, "R(T1,x2)") == "T1 reads x2: 20\n"
    assert step(tm, "R(T1,x3)") == "T1 reads x3: 30\n"
    assert step(tm, "begin(T2)") == ""
    assert step(tm, "R(T2,x2)") == "T2 reads x2: 22\n"
    assert tm.transactions["T2"].read_set[2] == ("T9", 2)


# --------------------------------------------------------- unreplicated

def test_unreplicated_down_site_waits():
    tm, out, _ = run_script("begin(T1)\nfail(4)\nR(T1,x3)\n")
    assert out == "T1 waits for site 4 to read x3\n"
    t1 = tm.transactions["T1"]
    assert t1.status is Status.WAITING
    assert t1.pending == parse_line("R(T1,x3)")
    assert tm.wait_queue == ["T1"]


def test_unreplicated_readable_right_after_recovery():
    # Test 6: odd variables have no other copy, so recovery is enough.
    _, out, _ = run_script("fail(4)\nrecover(4)\nbegin(T1)\nR(T1,x3)\n")
    assert out == "T1 reads x3: 30\n"


def test_waiting_transaction_ignores_new_ops():
    tm, _, err = run_script("begin(T1)\nfail(4)\nR(T1,x3)\nR(T1,x2)\n")
    assert "T1 is waiting" in err
    assert tm.wait_queue == ["T1"]


# ----------------------------------------------------------- replicated

def test_replicated_reads_from_any_valid_up_site():
    _, out, _ = run_script("fail(1)\nfail(2)\nbegin(T1)\nR(T1,x2)\n")
    assert out == "T1 reads x2: 20\n"


def test_replicated_all_down_but_valid_waits_for_all():
    # T1 began before any failure, so every site still has its snapshot.
    script = "begin(T1)\n" + fail_all_but() + "R(T1,x2)\n"
    tm, out, _ = run_script(script)
    assert out == "T1 waits for sites 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 to read x2\n"
    assert tm.transactions["T1"].status is Status.WAITING


def test_replicated_recovered_site_not_readable_for_new_txn():
    # Site 3 failed and recovered before T1 began, with no new commit to x2.
    # Every other site is down and failed before T1 began too, so abort.
    script = "fail(3)\nrecover(3)\n" + fail_all_but(3) + "begin(T1)\nR(T1,x2)\n"
    tm, out, _ = run_script(script)
    assert out == (
        "T1 aborts: no valid snapshot of x2 "
        "(no site up continuously from its last commit until T1 began)\n"
    )
    t1 = tm.transactions["T1"]
    assert t1.status is Status.ABORTED
    assert t1.abort_reason.startswith("no valid snapshot of x2")


def test_replicated_waits_only_for_qualifying_down_sites():
    # Sites 1-9 fail before T1 begins (no valid snapshot there). Site 10
    # fails after T1 begins, so it is the only site worth waiting for.
    script = fail_all_but(10) + "begin(T1)\nfail(10)\nR(T1,x2)\n"
    _, out, _ = run_script(script)
    assert out == "T1 waits for site 10 to read x2\n"


def test_old_snapshot_readable_after_recovery_without_new_commit():
    # Test 25: T1 began before site 2 failed, so site 2's copy is still T1's
    # snapshot after recovery, even though new transactions can't read it.
    script = "begin(T1)\n" + fail_all_but() + "recover(2)\nR(T1,x2)\nbegin(T2)\nR(T2,x2)\n"
    _, out, _ = run_script(script)
    assert out.splitlines() == [
        "T1 reads x2: 20",
        "T2 aborts: no valid snapshot of x2 "
        "(no site up continuously from its last commit until T2 began)",
    ]


def test_new_commit_makes_recovered_site_readable():
    script = "fail(5)\nrecover(5)\n" + fail_all_but(5)
    tm, _, _ = run_script(script)
    tm.sites[5].apply_commit(2, 55, tm.time + 1, "T9")
    tm.time += 1
    step(tm, "begin(T1)")
    assert step(tm, "R(T1,x2)") == "T1 reads x2: 55\n"


def test_failure_after_read_does_not_affect_snapshot():
    # §4.3.5: values already read stay valid; reading again is fine.
    script = "begin(T1)\nR(T1,x2)\nfail(1)\nR(T1,x2)\n"
    _, out, _ = run_script(script)
    assert out == "T1 reads x2: 20\nT1 reads x2: 20\n"


# ------------------------------------------------------------------ abort

def test_aborted_transaction_ignores_later_ops():
    script = "fail(3)\nrecover(3)\n" + fail_all_but(3) + "begin(T1)\nR(T1,x2)\nR(T1,x3)\n"
    tm, out, err = run_script(script)
    assert out.count("\n") == 1  # only the abort line
    assert "T1 already aborted" in err
