"""End-to-end regression tests.

For every tests/inputs/<name>.txt that has a matching tests/expected/<name>.txt,
run the simulator and compare stdout exactly. Expected outputs were traced by
hand from the comments in the course's SSI sample tests; the output format is
documented in PLAN.md ("Output format").
"""
import io
from pathlib import Path

import pytest

from repcrec.main import run

HERE = Path(__file__).parent
INPUTS = sorted((HERE / "inputs").glob("*.txt"))

# Scripts that can't pass yet because the features they need aren't built.
# strict=True: a listed script that starts passing FAILS the run, so remove it
# from this set as phases 5-8 land. Goal: empty set.
NOT_YET_PASSING = {
    "test25",  # needs retry of a blocked read on recover (Phase 8)
}


def _cases():
    for inp in INPUTS:
        exp = HERE / "expected" / inp.name
        marks = []
        if not exp.exists():
            marks.append(pytest.mark.skip(reason="no expected output"))
        elif inp.stem in NOT_YET_PASSING:
            marks.append(pytest.mark.xfail(strict=True, reason="feature not implemented yet"))
        yield pytest.param(inp, exp, id=inp.stem, marks=marks)


@pytest.mark.parametrize("inp, exp", list(_cases()))
def test_script(inp, exp):
    out = io.StringIO()
    with open(inp) as f:
        run(f, out, io.StringIO())
    assert out.getvalue() == exp.read_text()
