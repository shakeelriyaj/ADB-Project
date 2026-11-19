"""Line-oriented command parser.

Each input line is parsed independently (no look-ahead). A line may be:
  * blank or comment-only  -> parse_line returns None
  * one command            -> parse_line returns a Command
  * malformed              -> parse_line raises ParseError

Comments start with "//" and run to end of line. Command names are
case-insensitive and whitespace around parentheses/commas is ignored, e.g.
"W(T1,x2,5)", "w (t1, X2, 5)" and "W( T1 , x2 , 5 )" are all equivalent.
"""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from repcrec.placement import NUM_SITES, NUM_VARIABLES


class Kind(Enum):
    BEGIN = "begin"
    READ = "R"
    WRITE = "W"
    END = "end"
    FAIL = "fail"
    RECOVER = "recover"
    DUMP = "dump"
    QUERYSTATE = "querystate"


@dataclass(frozen=True)
class Command:
    kind: Kind
    tid: Optional[str] = None   # normalized "T<n>"
    var: Optional[int] = None   # variable index j for xj (1..20)
    value: Optional[int] = None  # value for W
    site: Optional[int] = None  # site id for fail/recover (1..10)


class ParseError(ValueError):
    pass


_LINE_RE = re.compile(r"^([A-Za-z]+)\s*\((.*)\)\s*;?$")
_TID_RE = re.compile(r"^[Tt](\d+)$")
_VAR_RE = re.compile(r"^[Xx](\d+)$")
_INT_RE = re.compile(r"^[+-]?\d+$")

# name (lowercase) -> (Kind, expected number of args)
_COMMANDS = {
    "begin": (Kind.BEGIN, 1),
    "r": (Kind.READ, 2),
    "w": (Kind.WRITE, 3),
    "end": (Kind.END, 1),
    "fail": (Kind.FAIL, 1),
    "recover": (Kind.RECOVER, 1),
    "dump": (Kind.DUMP, 0),
    "querystate": (Kind.QUERYSTATE, 0),
}


def strip_comment(line: str) -> str:
    idx = line.find("//")
    if idx != -1:
        line = line[:idx]
    return line.strip()


def _parse_tid(tok: str) -> str:
    m = _TID_RE.match(tok)
    if not m:
        raise ParseError(f"bad transaction id {tok!r}")
    return f"T{int(m.group(1))}"


def _parse_var(tok: str) -> int:
    m = _VAR_RE.match(tok)
    if not m:
        raise ParseError(f"bad variable {tok!r}")
    j = int(m.group(1))
    if not 1 <= j <= NUM_VARIABLES:
        raise ParseError(f"variable x{j} out of range 1..{NUM_VARIABLES}")
    return j


def _parse_int(tok: str, what: str) -> int:
    if not _INT_RE.match(tok):
        raise ParseError(f"bad {what} {tok!r}")
    return int(tok)


def _parse_site(tok: str) -> int:
    k = _parse_int(tok, "site")
    if not 1 <= k <= NUM_SITES:
        raise ParseError(f"site {k} out of range 1..{NUM_SITES}")
    return k


def parse_line(line: str) -> Optional[Command]:
    """Parse a single input line. Returns None for blank/comment lines."""
    text = strip_comment(line)
    if not text:
        return None

    m = _LINE_RE.match(text)
    if not m:
        raise ParseError(f"unrecognized line {text!r}")

    name, arg_str = m.group(1).lower(), m.group(2).strip()
    if name not in _COMMANDS:
        raise ParseError(f"unknown command {m.group(1)!r}")
    kind, nargs = _COMMANDS[name]

    args = [a.strip() for a in arg_str.split(",")] if arg_str else []
    if len(args) != nargs or any(a == "" for a in args):
        raise ParseError(f"{m.group(1)} expects {nargs} argument(s), got {arg_str!r}")

    if kind in (Kind.BEGIN, Kind.END):
        return Command(kind, tid=_parse_tid(args[0]))
    if kind is Kind.READ:
        return Command(kind, tid=_parse_tid(args[0]), var=_parse_var(args[1]))
    if kind is Kind.WRITE:
        return Command(
            kind,
            tid=_parse_tid(args[0]),
            var=_parse_var(args[1]),
            value=_parse_int(args[2], "value"),
        )
    if kind in (Kind.FAIL, Kind.RECOVER):
        return Command(kind, site=_parse_site(args[0]))
    return Command(kind)  # DUMP, QUERYSTATE
