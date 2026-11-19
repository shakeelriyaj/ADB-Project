"""Transaction Manager.

Phase 1/2 stub: accepts parsed commands but does nothing yet. The real
implementation arrives in Phase 4 onward.
"""
from typing import TextIO

from repcrec.parser import Command


class TransactionManager:
    def __init__(self, out: TextIO):
        self.out = out
        self.time = 0

    def process(self, cmd: Command, tick: int) -> None:
        """Execute one command at logical time `tick`."""
        self.time = tick
        # TODO(Phase 4+): dispatch on cmd.kind

    def advance(self, tick: int) -> None:
        """Called for lines with no command (blank/comment) so time still moves."""
        self.time = tick
