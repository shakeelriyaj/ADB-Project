"""Shared test helpers for driving a TransactionManager from script text."""
import io

from repcrec import placement
from repcrec.main import run
from repcrec.parser import parse_line


def run_script(script: str):
    out, err = io.StringIO(), io.StringIO()
    tm = run(io.StringIO(script), out, err)
    return tm, out.getvalue(), err.getvalue()


def step(tm, line: str) -> str:
    """Run one more command on an existing TM and return what it printed."""
    out = io.StringIO()
    tm.out = out
    tm.process(parse_line(line), tm.time + 1)
    return out.getvalue()


def fail_all_but(*keep: int) -> str:
    """Script lines failing every site not in `keep`."""
    return "".join(f"fail({s})\n" for s in placement.ALL_SITES if s not in keep)
