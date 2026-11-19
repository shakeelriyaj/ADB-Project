# RepCRec — Replicated Concurrency Control and Recovery

A simulated distributed database with SSI and Available Copies replication.
See `proposal.pdf` for the design and `PLAN.md` for the execution plan.

## Requirements
- Python 3.10+
- `pytest` for tests (`pip install -r requirements-dev.txt`)

## Run
```
python3 -m repcrec path/to/input.txt   # from a file
python3 -m repcrec < path/to/input.txt # from stdin
```

## Test
```
python3 -m pytest
```
End-to-end tests: put a script in `tests/inputs/<name>.txt` and its expected
output in `tests/expected/<name>.txt`.

## Layout
```
repcrec/
  main.py         entry point; reads input line by line, one tick per line
  parser.py       line -> Command
  tm.py           Transaction Manager
  dm.py           Data Manager (one per site)
  transaction.py  Transaction object
  graph.py        serialization graph / SSI cycle detection
tests/
```
