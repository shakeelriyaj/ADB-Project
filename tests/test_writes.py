"""Phase 6: write rules (proposal §4.4)."""
from repcrec import placement
from repcrec.parser import parse_line
from repcrec.transaction import Status
from tests.helpers import fail_all_but, run_script, step

ALL = "sites 1, 2, 3, 4, 5, 6, 7, 8, 9, 10"


def test_write_replicated_goes_to_all_up_sites():
    tm, out, err = run_script("begin(T1)\nW(T1,x2,202)\n")
    assert out == f"T1 writes x2: 202 to {ALL}\n"
    assert err == ""
    t1 = tm.transactions["T1"]
    assert t1.write_buffer == {2: 202}
    assert t1.write_sites == {2: set(placement.ALL_SITES)}
    assert t1.first_write_at_site == {s: 2 for s in placement.ALL_SITES}


def test_write_unreplicated_goes_to_home_site():
    tm, out, _ = run_script("begin(T1)\nW(T1,x1,101)\nW(T1,x13,7)\n")
    assert out == "T1 writes x1: 101 to site 2\nT1 writes x13: 7 to site 4\n"
    assert tm.transactions["T1"].write_sites == {1: {2}, 13: {4}}


def test_write_skips_down_sites():
    # Test 3: W(T2,x8,88) while site 2 is down.
    tm, out, _ = run_script("begin(T1)\nfail(2)\nfail(7)\nW(T1,x8,88)\n")
    assert out == "T1 writes x8: 88 to sites 1, 3, 4, 5, 6, 8, 9, 10\n"
    assert tm.transactions["T1"].write_sites[8] == {1, 3, 4, 5, 6, 8, 9, 10}


def test_write_to_recovered_site_is_allowed_immediately():
    # Test 3.7: a recovered site accepts writes right away.
    _, out, _ = run_script("begin(T1)\nfail(2)\nrecover(2)\nW(T1,x4,91)\n")
    assert out == f"T1 writes x4: 91 to {ALL}\n"


def test_write_does_not_touch_site_data_before_commit():
    tm, _, _ = run_script("begin(T1)\nW(T1,x2,5)\nW(T1,x1,6)\n")
    assert all(tm.sites[s].latest_version(2).value == 20 for s in placement.ALL_SITES)
    assert tm.sites[2].latest_version(1).value == 10


def test_rewrite_keeps_latest_value_and_first_write_time():
    tm, out, _ = run_script("begin(T1)\nW(T1,x2,1)\nfail(3)\nW(T1,x2,2)\nR(T1,x2)\n")
    assert out.splitlines()[-1] == "T1 reads x2: 2"
    t1 = tm.transactions["T1"]
    assert t1.write_buffer == {2: 2}
    assert t1.first_write_at_site[1] == 2      # from the first write
    assert 3 in t1.write_sites[2]             # site 3 was written before it failed


def test_write_unreplicated_site_down_waits():
    tm, out, _ = run_script("begin(T1)\nfail(4)\nW(T1,x3,33)\n")
    assert out == "T1 waits for site 4 to write x3\n"
    t1 = tm.transactions["T1"]
    assert t1.status is Status.WAITING
    assert t1.pending == parse_line("W(T1,x3,33)")
    assert t1.write_buffer == {}               # nothing buffered while blocked
    assert tm.wait_queue == ["T1"]


def test_write_replicated_all_sites_down_waits():
    tm, out, _ = run_script("begin(T1)\n" + fail_all_but() + "W(T1,x2,5)\n")
    assert out == f"T1 waits for {ALL} to write x2\n"
    assert tm.transactions["T1"].status is Status.WAITING


def test_write_with_one_site_up():
    # FAQ scenario (1): all sites fail, site 5 recovers; the write goes to site 5.
    tm, out, _ = run_script(fail_all_but() + "recover(5)\nbegin(T2)\nW(T2,x6,131)\n")
    assert out == "T2 writes x6: 131 to site 5\n"


def test_sample_script_write_lines():
    """The W lines of Test 15 match the expected output, in order."""
    tm, _, _ = run_script("begin(T5)\nbegin(T4)\nbegin(T3)\nbegin(T2)\nbegin(T1)\n")
    assert step(tm, "W(T1,x4, 5)") == f"T1 writes x4: 5 to {ALL}\n"
    step(tm, "fail(2)")
    assert step(tm, "W(T2,x4,44)") == "T2 writes x4: 44 to sites 1, 3, 4, 5, 6, 7, 8, 9, 10\n"
    step(tm, "recover(2)")
    assert step(tm, "W(T3,x4,55)") == f"T3 writes x4: 55 to {ALL}\n"
