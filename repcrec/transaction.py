"""Transaction object (proposal §4.1)."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Set, Tuple

from repcrec.parser import Command


class Status(Enum):
    ACTIVE = "active"
    WAITING = "waiting"      # blocked on a down site; `pending` holds the op
    COMMITTED = "committed"
    ABORTED = "aborted"


@dataclass
class Transaction:
    tid: str
    begin_time: int
    status: Status = Status.ACTIVE

    # var -> latest value written by this transaction (applied only at commit)
    write_buffer: Dict[int, int] = field(default_factory=dict)
    # var -> sites that were up when this transaction wrote var. At commit the
    # value goes to exactly these sites, never to sites that recovered later
    # (Test 3.5).
    write_sites: Dict[int, Set[int]] = field(default_factory=dict)
    # site -> time of this transaction's first write there (Available Copies rule)
    first_write_at_site: Dict[int, int] = field(default_factory=dict)
    # var -> (writer tid, commit_time) of the committed version read. Reads of
    # the transaction's own buffered writes are not recorded.
    read_set: Dict[int, Tuple[str, int]] = field(default_factory=dict)

    pending: Optional[Command] = None   # op blocked while WAITING
    commit_time: Optional[int] = None
    abort_reason: Optional[str] = None

    @property
    def is_live(self) -> bool:
        """Still running (active or waiting): can still commit or abort."""
        return self.status in (Status.ACTIVE, Status.WAITING)

    @property
    def write_set(self) -> Set[int]:
        return set(self.write_buffer)

    def record_write(self, var: int, value: int, sites, t: int) -> None:
        self.write_buffer[var] = value
        self.write_sites.setdefault(var, set()).update(sites)
        for s in sites:
            self.first_write_at_site.setdefault(s, t)

    def record_read(self, var: int, writer: str, commit_time: int) -> None:
        self.read_set.setdefault(var, (writer, commit_time))
