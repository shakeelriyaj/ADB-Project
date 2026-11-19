from pathlib import Path

import pytest

from repcrec.parser import Command, Kind, ParseError, parse_line


@pytest.mark.parametrize(
    "line, expected",
    [
        ("begin(T1)", Command(Kind.BEGIN, tid="T1")),
        ("Begin (t12)", Command(Kind.BEGIN, tid="T12")),
        ("R(T1, x4)", Command(Kind.READ, tid="T1", var=4)),
        ("r( T2 ,X20 )", Command(Kind.READ, tid="T2", var=20)),
        ("W(T1,x2,5)", Command(Kind.WRITE, tid="T1", var=2, value=5)),
        ("W (T1, x2, -7)", Command(Kind.WRITE, tid="T1", var=2, value=-7)),
        ("end(T1)", Command(Kind.END, tid="T1")),
        ("End (T3)", Command(Kind.END, tid="T3")),
        ("fail(3)", Command(Kind.FAIL, site=3)),
        ("recover(10)", Command(Kind.RECOVER, site=10)),
        ("dump()", Command(Kind.DUMP)),
        ("dump( )", Command(Kind.DUMP)),
        ("querystate()", Command(Kind.QUERYSTATE)),
        ("  W(T1,x2,5)   // trailing comment", Command(Kind.WRITE, tid="T1", var=2, value=5)),
        ("begin(T1);", Command(Kind.BEGIN, tid="T1")),
    ],
)
def test_valid_commands(line, expected):
    assert parse_line(line) == expected


@pytest.mark.parametrize("line", ["", "   ", "\n", "// comment only", "   // indented comment"])
def test_blank_and_comment_lines(line):
    assert parse_line(line) is None


@pytest.mark.parametrize(
    "line",
    [
        "begin T1",            # no parens
        "start(T1)",           # unknown command
        "begin()",             # missing arg
        "begin(T1, T2)",       # too many args
        "R(T1)",               # too few args
        "R(T1, y3)",           # bad var
        "R(T1, x0)",           # var out of range
        "R(T1, x21)",          # var out of range
        "W(T1, x2, abc)",      # bad value
        "W(T1, x2,)",          # empty arg
        "fail(0)",             # site out of range
        "fail(11)",            # site out of range
        "recover(a)",          # bad site
        "dump(1)",             # unexpected arg
        "begin(1)",            # bad tid
    ],
)
def test_malformed(line):
    with pytest.raises(ParseError):
        parse_line(line)

SAMPLE_INPUTS = sorted((Path(__file__).parent / "inputs").glob("*.txt"))


@pytest.mark.parametrize("path", SAMPLE_INPUTS, ids=lambda p: p.stem)
def test_sample_inputs_parse_cleanly(path):
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        try:
            parse_line(line)
        except ParseError as e:
            pytest.fail(f"{path.name}:{lineno}: {e}")
