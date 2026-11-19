"""Entry point: reads commands one line at a time and feeds them to the TM.

Usage:
    python -m repcrec [input_file]     # reads stdin if no file given

Every input line, including blank and comment-only lines, advances logical
time by one tick. Malformed lines are reported on stderr and skipped (they
still consume a tick).
"""
import sys
from typing import Iterable, Optional, TextIO

from repcrec.parser import ParseError, parse_line
from repcrec.tm import TransactionManager


def run(lines: Iterable[str], out: TextIO, err: TextIO = sys.stderr) -> TransactionManager:
    tm = TransactionManager(out, err)
    tick = 0
    for lineno, line in enumerate(lines, start=1):
        tick += 1
        try:
            cmd = parse_line(line)
        except ParseError as e:
            print(f"line {lineno}: parse error: {e}", file=err)
            tm.advance(tick)
            continue
        if cmd is None:
            tm.advance(tick)
        else:
            tm.process(cmd, tick)
    return tm


def main(argv: Optional[list] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) > 1:
        print("usage: python -m repcrec [input_file]", file=sys.stderr)
        return 2
    if argv:
        with open(argv[0]) as f:
            run(f, sys.stdout)
    else:
        run(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
