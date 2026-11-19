"""End-to-end regression tests.

For every tests/inputs/<name>.txt that has a matching tests/expected/<name>.txt,
run the simulator and compare stdout exactly.
"""
import io
from pathlib import Path

import pytest

from repcrec.main import run

HERE = Path(__file__).parent
INPUTS = sorted((HERE / "inputs").glob("*.txt"))


def _cases():
    for inp in INPUTS:
        exp = HERE / "expected" / inp.name
        yield pytest.param(inp, exp, id=inp.stem,
                           marks=[] if exp.exists() else pytest.mark.skip(reason="no expected output"))


@pytest.mark.parametrize("inp, exp", list(_cases()))
def test_script(inp, exp):
    out = io.StringIO()
    with open(inp) as f:
        run(f, out)
    assert out.getvalue() == exp.read_text()
