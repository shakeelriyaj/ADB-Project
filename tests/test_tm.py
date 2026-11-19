import io
from pathlib import Path

import pytest

from repcrec.main import run
from repcrec.parser import parse_line
from repcrec.transaction import Status, Transaction
from tests.helpers import run_script


# ---------------------------------------------------------------- Transaction

def test_transaction_record_write_tracks_sites_and_first_write():
    t = Transaction("T1", begin_time=1)
    t.record_write(2, 5, [1, 3, 4], t=3)
    t.record_write(2, 6, [1, 2, 3, 4], t=7)   # site 2 recovered in between
    t.record_write(4, 9, [1, 2], t=8)
    assert t.write_buffer == {2: 6, 4: 9}
    assert t.write_sites == {2: {1, 2, 3, 4}, 4: {1, 2}}
    assert t.first_write_at_site == {1: 3, 3: 3, 4: 3, 2: 7}
    assert t.write_set == {2, 4}


def test_transaction_record_read_keeps_first_version():
    t = Transaction("T1", begin_time=1)
    t.record_read(3, "T0", 0)
    t.record_read(3, "T9", 5)  # snapshot reads can't change; keep the first
    assert t.read_set == {3: ("T0", 0)}


@pytest.mark.parametrize(
    "status, live",
    [(Status.ACTIVE, True), (Status.WAITING, True),
     (Status.COMMITTED, False), (Status.ABORTED, False)],
)
def test_transaction_is_live(status, live):
    assert Transaction("T1", 1, status=status).is_live is live


# ----------------------------------------------------------------------- begin

def test_begin_records_tick_as_begin_time():
    tm, out, err = run_script("// c\n\nbegin(T1)\nbegin(T2)\n")
    assert tm.transactions["T1"].begin_time == 3
    assert tm.transactions["T2"].begin_time == 4
    assert tm.transactions["T1"].status is Status.ACTIVE
    assert out == "" and err == ""


def test_duplicate_begin_warns_and_keeps_original():
    tm, _, err = run_script("begin(T1)\nbegin(T1)\n")
    assert tm.transactions["T1"].begin_time == 1
    assert "T1 already exists" in err


def test_op_on_unknown_transaction_warns():
    _, out, err = run_script("R(T9,x2)\n")
    assert out == ""
    assert "T9 has not begun" in err


def test_op_on_finished_transaction_warns():
    tm, _, _ = run_script("begin(T1)\n")
    tm.transactions["T1"].status = Status.ABORTED
    err = io.StringIO()
    tm.err = err
    tm.process(parse_line("W(T1,x2,5)"), 2)
    assert "T1 already aborted" in err.getvalue()


# ---------------------------------------------------------- fail / recover

def test_fail_and_recover_update_site_and_history():
    tm, out, _ = run_script("fail(3)\n\nrecover(3)\nfail(3)\n")
    dm = tm.sites[3]
    assert not dm.is_up
    assert dm.down_intervals == [(1, 3), (4, None)]
    assert all(tm.sites[s].is_up for s in tm.sites if s != 3)
    assert out == ""  # fail/recover produce no required output


# ------------------------------------------------------------------- dump

def test_initial_dump():
    _, out, _ = run_script("dump()\n")
    lines = out.splitlines()
    assert len(lines) == 10
    assert lines[0] == (
        "site 1 - x2: 20, x4: 40, x6: 60, x8: 80, x10: 100, "
        "x12: 120, x14: 140, x16: 160, x18: 180, x20: 200"
    )
    assert lines[1].startswith("site 2 - x1: 10, x2: 20, ")
    assert "x11: 110" in lines[1]
    assert lines[9].startswith("site 10 - x2: 20, ")
    assert "x9: 90" in lines[9] and "x19: 190" in lines[9]


def test_dump_includes_down_sites():
    _, out, _ = run_script("fail(4)\ndump()\n")
    assert out.splitlines()[3].startswith("site 4 - x2: 20, x3: 30, ")


# -------------------------------------------------------------- querystate

def test_querystate_shows_sites_transactions_and_data():
    _, out, _ = run_script("begin(T1)\nfail(2)\nrecover(2)\nquerystate()\n")
    assert "=== querystate @ t=4 ===" in out
    assert "site 2: up; outages: [2,3)" in out
    assert "site 1: up; outages: none" in out
    assert "T1: active; begin=1" in out
    assert "Wait queue: (empty)" in out
    # site 2 after recovery: replicated x2 unreadable, unreplicated x1 fine
    assert "site 2 - x1: 10, x2: 20*," in out


def test_sample_scripts_run_without_crashing():
    """Smoke test: every sample script runs end to end with the Phase 4 TM."""
    for path in sorted((Path(__file__).parent / "inputs").glob("*.txt")):
        out, err = io.StringIO(), io.StringIO()
        with open(path) as f:
            run(f, out, err)
        assert "parse error" not in err.getvalue(), path.name
