"""Static data placement rules (proposal §4.2).

* Variables x1..x20, initial value 10*i.
* Even i: replicated at every site 1..10.
* Odd i: stored only at site 1 + (i mod 10).
"""
from typing import List

NUM_VARIABLES = 20
NUM_SITES = 10
ALL_SITES = tuple(range(1, NUM_SITES + 1))
ALL_VARIABLES = tuple(range(1, NUM_VARIABLES + 1))


def is_replicated(var: int) -> bool:
    return var % 2 == 0


def home_site(var: int) -> int:
    """Only site for an unreplicated (odd) variable."""
    if is_replicated(var):
        raise ValueError(f"x{var} is replicated; it has no single home site")
    return 1 + var % 10


def sites_for(var: int) -> List[int]:
    """All sites holding a copy of xvar, ascending."""
    return list(ALL_SITES) if is_replicated(var) else [home_site(var)]


def variables_at(site: int) -> List[int]:
    """All variables stored at `site`, ascending."""
    return [v for v in ALL_VARIABLES if site in sites_for(v)]


def initial_value(var: int) -> int:
    return 10 * var
