import pytest

from repcrec import placement
from repcrec.dm import INITIAL_TID, DataManager, SiteDownError, Version


# ------------------------------------------------------------- placement

def test_placement_rules():
    assert placement.sites_for(2) == list(range(1, 11))
    assert placement.sites_for(1) == [2]
    assert placement.sites_for(11) == [2]
    assert placement.sites_for(3) == [4]
    assert placement.sites_for(13) == [4]
    assert placement.sites_for(9) == [10]
    assert placement.sites_for(19) == [10]


def test_site_contents():
    # Site 1 holds no odd variables (1 + i mod 10 == 1 needs i mod 10 == 0, i.e. even).
    assert placement.variables_at(1) == list(range(2, 21, 2))
    # Site 2 holds x1, x11 plus all evens.
    assert placement.variables_at(2) == sorted([1, 11] + list(range(2, 21, 2)))
    every_var_somewhere = set()
    for s in placement.ALL_SITES:
        every_var_somewhere |= set(placement.variables_at(s))
    assert every_var_somewhere == set(placement.ALL_VARIABLES)


def test_home_site_rejects_replicated():
    with pytest.raises(ValueError):
        placement.home_site(4)


# ---------------------------------------------------------- initial data

def test_initial_versions():
    dm = DataManager(4)
    assert dm.holds(3) and dm.holds(13) and dm.holds(2)
    assert not dm.holds(1)
    assert dm.latest_version(3) == Version(30, 0, INITIAL_TID)
    assert dm.latest_version(20) == Version(200, 0, INITIAL_TID)
    assert dm.is_up


def test_dump_line_initial():
    assert DataManager(1).dump_line() == (
        "site 1 - x2: 20, x4: 40, x6: 60, x8: 80, x10: 100, "
        "x12: 120, x14: 140, x16: 160, x18: 180, x20: 200"
    )
    assert DataManager(2).dump_line().startswith("site 2 - x1: 10, x2: 20, x4: 40")


# ------------------------------------------------------------- versions

def test_version_as_of():
    dm = DataManager(1)
    dm.apply_commit(2, 22, 5, "T1")
    dm.apply_commit(2, 23, 9, "T2")
    assert dm.version_as_of(2, 0).value == 20
    assert dm.version_as_of(2, 4).value == 20
    assert dm.version_as_of(2, 5).value == 22
    assert dm.version_as_of(2, 8).value == 22
    assert dm.version_as_of(2, 100) == Version(23, 9, "T2")
    assert dm.latest_version(2).value == 23


def test_apply_commit_rejects_down_site_and_foreign_var():
    dm = DataManager(1)
    with pytest.raises(KeyError):
        dm.apply_commit(1, 5, 3, "T1")  # x1 lives at site 2
    dm.fail(4)
    with pytest.raises(SiteDownError):
        dm.apply_commit(2, 5, 5, "T1")


# ---------------------------------------------------- failure / recovery

def test_fail_keeps_committed_data():
    dm = DataManager(2)
    dm.apply_commit(1, 11, 3, "T1")
    dm.fail(5)
    assert not dm.is_up
    assert dm.latest_version(1).value == 11
    assert "x1: 11" in dm.dump_line()  # dump shows down sites too


def test_recover_readable_flags():
    dm = DataManager(2)
    dm.fail(3)
    dm.recover(6)
    assert dm.is_up
    assert dm.readable[1] and dm.readable[11]       # unreplicated: readable
    assert not dm.readable[2] and not dm.readable[4]  # replicated: wait for a commit
    dm.apply_commit(2, 99, 8, "T1")
    assert dm.readable[2]
    assert not dm.readable[4]


def test_fail_recover_are_idempotent():
    dm = DataManager(3)
    dm.recover(2)              # already up: no-op
    assert dm.down_intervals == []
    dm.fail(3)
    dm.fail(4)                 # already down: no-op
    assert dm.down_intervals == [(3, None)]
    dm.recover(6)
    assert dm.down_intervals == [(3, 6)]


def test_was_up_throughout():
    dm = DataManager(1)
    dm.fail(5)
    dm.recover(8)
    dm.fail(12)
    assert dm.was_up_throughout(0, 4)
    assert not dm.was_up_throughout(0, 5)    # failure at the end point
    assert not dm.was_up_throughout(6, 7)    # entirely inside the outage
    assert not dm.was_up_throughout(2, 10)   # spans the outage
    assert dm.was_up_throughout(8, 11)       # recovered at 8
    assert not dm.was_up_throughout(9, 20)   # still down since 12


def test_failed_between():
    dm = DataManager(1)
    dm.fail(5)
    dm.recover(8)
    assert dm.failed_between(4, 5)
    assert dm.failed_between(1, 10)
    assert not dm.failed_between(5, 10)      # failure exactly at start does not count
    assert not dm.failed_between(6, 10)      # still in that outage; no new failure


def test_test25_scenario_old_snapshot_still_valid():
    """Site 2 committed x8 at t=11, failed at t=22 after T3 began at t=21."""
    dm = DataManager(2)
    dm.apply_commit(8, 88, 11, "T2")
    dm.fail(22)
    dm.recover(28)
    v = dm.version_as_of(8, 21)
    assert v.value == 88
    assert dm.was_up_throughout(v.commit_time, 21)  # T3 may read it after recovery
    assert not dm.readable[8]                        # but new transactions may not
