import io

from repcrec import main as main_mod
from repcrec.parser import Kind


class RecordingTM:
    """Stands in for TransactionManager to observe dispatch and ticks."""

    def __init__(self, out, err=None):
        self.calls = []

    def process(self, cmd, tick):
        self.calls.append((tick, cmd.kind))

    def advance(self, tick):
        self.calls.append((tick, None))


def test_every_line_advances_time(monkeypatch):
    monkeypatch.setattr(main_mod, "TransactionManager", RecordingTM)
    script = "begin(T1)\n\n// comment\nbogus line\nR(T1,x2)\nend(T1)\n"
    err = io.StringIO()
    tm = main_mod.run(io.StringIO(script), io.StringIO(), err)
    assert tm.calls == [
        (1, Kind.BEGIN),
        (2, None),
        (3, None),
        (4, None),  # parse error still consumes a tick
        (5, Kind.READ),
        (6, Kind.END),
    ]
    assert "line 4: parse error" in err.getvalue()


def test_main_reads_file(tmp_path, capsys):
    f = tmp_path / "in.txt"
    f.write_text("begin(T1)\nend(T1)\n")
    assert main_mod.main([str(f)]) == 0
