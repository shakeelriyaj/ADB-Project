"""Phase 7: serialization graph / dangerous-cycle detection, in isolation."""
from repcrec.graph import RW, WR, WW, SerializationGraph, _has_consecutive_rw


def test_consecutive_rw_detection_wraps_around():
    assert _has_consecutive_rw([RW, RW])
    assert _has_consecutive_rw([WW, RW, RW])
    assert _has_consecutive_rw([RW, WW, RW])      # last -> first wraps
    assert not _has_consecutive_rw([RW, WR, RW, WR])
    assert not _has_consecutive_rw([RW])
    assert not _has_consecutive_rw([])


def test_two_node_rw_cycle():
    # Test 21: T2 -rw-> T1 committed... T1 -rw-> T2 closes it.
    g = SerializationGraph()
    assert g.has_dangerous_cycle("T2", [("T2", "T1", RW), ("T1", "T2", RW)])


def test_one_direction_only_is_not_a_cycle():
    # Test 2: both of T2's edges point at T1.
    g = SerializationGraph()
    assert not g.has_dangerous_cycle("T2", [("T2", "T1", RW), ("T2", "T1", RW)])


def test_cycle_without_consecutive_rw_is_allowed():
    g = SerializationGraph()
    g.add_edges([("T1", "T2", RW), ("T2", "T3", WR)])
    assert not g.has_dangerous_cycle("T3", [("T3", "T1", WW)])   # rw, wr, ww


def test_long_rw_cycle_through_committed_nodes():
    # Test 18: T4 -> T3 -> T2 -> T1 already committed; T5 closes the loop.
    g = SerializationGraph()
    g.add_edges([("T4", "T3", RW), ("T3", "T2", RW), ("T2", "T1", RW)])
    assert g.has_dangerous_cycle("T5", [("T1", "T5", RW), ("T5", "T4", RW)])


def test_cycle_must_pass_through_committing_txn():
    g = SerializationGraph()
    g.add_edges([("T1", "T2", RW), ("T2", "T1", RW)])     # pre-existing, unrelated
    assert not g.has_dangerous_cycle("T3", [("T1", "T3", WR)])


def test_mixed_edge_cycle_test22():
    g = SerializationGraph()
    g.add_edges([("T2", "T1", RW)])
    assert g.has_dangerous_cycle("T3", [("T1", "T3", WW), ("T3", "T2", RW)])


def test_check_does_not_modify_graph():
    g = SerializationGraph()
    g.has_dangerous_cycle("T1", [("T1", "T2", RW)])
    assert g.edges() == []
    g.add_edges([("T1", "T2", RW)])
    assert g.edges() == [("T1", "T2", RW)]
