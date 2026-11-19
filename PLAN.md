# RepCRec — Execution Plan

Based on `proposal.pdf`. This plan assumes **Python 3**; nothing in the proposal names a language, so swap it if your course requires another.

---

## 0. Summary of the system

- **1 Transaction Manager (TM):** never fails. Owns the clock, the transaction table, site up/down history, the wait queue, and the serialization graph.
- **10 Data Managers (DMs), one per site:** store multiversion committed data and may fail or recover.
- **Data:** `x1..x20`, initial value `10*i`.
  - Even `i`: replicated at sites 1–10.
  - Odd `i`: stored only at site `1 + (i mod 10)`. So x1 and x11 are at site 2, x3 and x13 at site 4, and so on.
- **Concurrency control:** SSI. Reads come from the snapshot at begin time, writes are buffered, and validation happens at `end(T)`.
- **Replication:** Available Copies, with the write-abort rule.

---

## Phase 1 — Project skeleton (day 1)

1. Set up the repo layout:
   ```
   repcrec/
     __init__.py
     main.py            # entry point: python -m repcrec [file]  (stdin if no file)
     parser.py          # line -> Command
     tm.py              # TransactionManager
     dm.py              # DataManager (site)
     transaction.py     # Transaction dataclass
     graph.py           # serialization graph + dangerous-cycle check
   tests/
     inputs/            # .txt test scripts
     expected/          # expected outputs
     test_*.py          # pytest
   README.md
   ```
2. Add `pytest` and a simple runner script that runs every file in `tests/inputs` and diffs the output against `tests/expected`.

## Phase 2 — Parser (day 1)

1. Read input **one line at a time** from a file or stdin, with no look-ahead.
2. Strip comments (`//...`) and whitespace. Matching is case-insensitive for `begin`, `R`, `W`, `end`, `fail`, `recover`, `dump`, and `querystate`.
3. Accept loose spacing, for example `W(T1, x2, 5)` and `W (T1,x2,5)`.
4. **Every line advances the tick by 1, including blank and comment-only lines.** Increment the tick before dispatching.
5. Unit tests: one per command form and one for malformed input.

## Phase 3 — Data Manager (days 2–3)

1. `Version(value, commit_time, writer_tid)`.
2. `DataManager(site_id)` state:
   - `versions: dict[var -> list[Version]]`, seeded at time 0 with `10*i`.
   - `is_up: bool`.
   - `readable: dict[var -> bool]` for replicated vars. Set it to False on recovery and back to True when a new commit lands.
3. Methods:
   - `latest_version_before(var, t)`
   - `apply_commit(var, value, t, tid)`: appends a version and marks the var readable.
   - `fail()`: marks the site down and clears volatile state. Committed versions stay.
   - `recover()`: marks the site up. Replicated vars become unreadable; unreplicated vars stay readable.
   - `dump_line()`: `site k - x2: 20, x4: 40, ...` in ascending variable order, including down sites.
4. Unit tests: initial placement, version lookup, and the effects of fail and recover.

## Phase 4 — Transaction & TM basics (days 3–4)

1. `Transaction` fields: `tid`, `begin_time`, `status` (ACTIVE/WAITING/COMMITTED/ABORTED), `write_buffer {var: value}`, `sites_written {site: first_write_time}`, `read_set {var: (writer_tid, version_time)}`, `write_set`, `pending_op`, and `commit_time`.
2. TM state:
   - The 10 `DataManager`s. Each site keeps its own failure history, so use `dm.was_up_throughout(t1, t2)` and `dm.failed_between(t1, t2)`. This was done in Phase 3.
   - A global commit log per variable for first-committer-wins. A site that was down may have missed commits, so no single site's versions are complete.
3. Implement `begin`, `fail`, `recover`, `dump`, and `querystate`. `querystate` prints the transaction table, site status and history, the wait queue, graph edges, and the per-site values.

## Phase 5 — Reads (days 4–5)

Follow proposal §4.3 exactly:

1. If T already wrote `xj`, return the buffered value.
2. **Unreplicated:** if the site is up, return the latest version with `commit_time <= T.begin`. Otherwise **wait** and print `Ti waits for site k`.
3. **Replicated:** for each site `s`, take `v = latest_version_before(xj, T.begin)` and check that `s` was continuously up from `v.commit_time` through `T.begin`.
   - If any such `s` is **up now**, read `v` from it.
   - If some qualify but are all down, **wait**.
   - If none qualify, **abort** with the message "no site with valid snapshot of xj".
4. Record the read in `read_set` with the writer TID; this is needed for the WR and RW edges. Print `xj: value`.

Tests: read-your-own-write, snapshot isolation, wait on a down unreplicated site, abort when all replicas failed after the last commit, and a recovered site that is not readable until a new commit.

## Phase 6 — Writes (day 5)

1. Buffer the value in `write_buffer`.
2. Determine the up sites that hold `xj`.
   - If there are none, **wait** (§4.4). See the open questions below for the replicated case.
   - Otherwise record `sites_written[s] = now` the first time for each site, and print `W(Ti, xj, v) -> sites: [..]`.

## Phase 7 — Commit validation (days 6–8, the core)

At `end(T)`, check in this order and print the reason that fired:

1. **Available Copies:** for any `s` in `sites_written`, `s` failed at a time within `(first_write_time, now)`. Abort with the message "site s failed after write".
2. **First committer wins:** for any `x` in `write_set`, there is a committed version of `x` with `commit_time > T.begin`. Abort.
3. **SSI dangerous structure:**
   - Build T's candidate edges against **committed** transactions:
     - **WW:** `T1 -> T2` if both wrote `x` and T1 committed first.
     - **WR:** `T1 -> T2` if T2 read the version T1 wrote.
     - **RW:** `T1 -> T2` if T1 read `x` and T2 wrote a newer version of `x`. Concurrent transactions only.
   - Add T's edges tentatively and run a DFS for any cycle through T that contains **two consecutive RW edges**. Track the previous edge type along the path, and include the wrap-around edge pair. If such a cycle exists, abort.
4. Otherwise **commit**:
   - `commit_time = now`.
   - Apply each buffered write to the sites in **`sites_written`** for that variable, meaning the sites that were up at write time. Don't write to a site that recovered later (Test 3.5). By this point the Available Copies check guarantees those sites are still up.
   - Add T to the graph permanently.
5. On abort, discard the buffer and remove T from the wait queue.
6. Do not garbage-collect committed transactions from the graph (see Test 22 below).

Tests (the classic cases): write skew (must abort), lost update (FCW), read-only anomaly, a site failure between write and end, and a write before a site recovers.

## Phase 8 — Waiting & retry (day 8)

1. Keep a FIFO wait queue of `(T, pending_op)`.
2. On `recover(k)`, retry the waiting operations in FIFO order. A retried read still uses T's **original** snapshot (`begin_time`).
3. Do not process any new operations for a waiting T. The proposal relies on scripts not doing that; add an assert or warning.

## Phase 9 — Output polish (day 9)

Write a single `output.py` with all the message formats so they stay consistent:
- `x4: 40`
- `T1 commits` / `T1 aborts (reason)`
- `W(T1,x4,5) -> sites 1,2,3...`
- `T2 waits for site 4` / `T2 resumes`
- `site 1 - x2: 20, x4: 40, ...` (dump)

## Phase 10 — Testing (days 9–11)

1. Split the 27 SSI sample tests (1–25, plus 3.5 and 3.7, from the course PDF) into `tests/inputs/` and write hand-verified expected output for each. The FAQ warns that graders will use other cases too.
2. Add our own edge-case scripts:
   - Fail and recover the same site repeatedly.
   - Commit while every replica of a variable is down.
   - Read a replicated var right after its site recovers, both before and after a new commit.
   - A transaction that began before a failure reads after the failure (§4.3.5).
   - A 3-transaction SSI cycle, and a cycle with RW edges that are **not** consecutive (must commit).
   - A waiting transaction resumes after `recover`.
3. Run `pytest` in CI or before each merge.

## Phase 11 — Deliverables (days 11–12)

1. A README with build and run instructions (`python -m repcrec input.txt`).
2. A design document covering the architecture diagram, data structures, and the read, write, and commit algorithms. Much of this can come from the proposal.
3. Source code documentation: a header comment per file and per function giving inputs, outputs, and side effects.
4. Any packaging or reproducibility requirement from the course, such as a ReproZip bundle, if your syllabus asks for one.

---

## Suggested split (two people)

| Shakeel | Shen |
|---|---|
| Parser, DM, failure/recovery history | Transaction object, TM read/write paths |
| Commit validation: Available Copies + FCW | Serialization graph + dangerous-cycle DFS |
| Wait queue/retry | Test harness + test scripts |
| Design doc | README / packaging |

Integrate at the end of Phase 6 and again after Phase 8.

---

## Resolved by the FAQ + SSI sample tests

Sources: `FinalProject_FAQs (1).pdf` and the SSI sample tests PDF. The FAQ is titled "When locking is used", so its answers about read and wait semantics come from the locking variant of the project. **Where they disagree, the SSI sample tests take precedence.**

1. **`end(Ti)` while Ti is waiting:** this never happens. The FAQ says "We will never do that." Print a warning on stderr if it does.
2. **FCW window:** confirmed as `commit_time > T.begin`. Tests 1, 13, 14, 15 and 20 all follow this rule. In Test 15, T3, T4 and T5 abort because T2 committed x4 first.
3. **Edges to active transactions:** check **only against committed transactions**. Test 18 confirms it: the 5-way RW cycle exists among active transactions when T4 ends, yet T4, T3, T2 and T1 all commit and only T5, which closes the cycle, aborts.
4. **WW and WR edges are NOT limited to concurrent pairs.** In Test 22, T3 aborts using the edge `T1 -ww-> T3` even though T1 committed before T3 began. Only RW edges imply concurrency.
5. **Aborted transactions:** their writes are discarded and they never enter the graph (Tests 17 and 19).

## Corrections to the plan found in the tests

- **Commit writes go to `sites_written`, not to "sites up at commit".** Test 3.5: `W(T1,x4,91)` is issued while site 2 is down, site 2 recovers before `end(T1)`, and site 2 does **not** get 91. There is "no retroactive write". This corrects proposal §4.5 and Phase 7.4 above.
- **The read rule must use the failure history, not a "readable" flag.** Test 25: T3 began before site 2 failed and site 2 later recovers. T3 then reads 88 from site 2 even though no new commit has landed there. The rule "site up continuously from the version's commit until T.begin" handles both this case and the "recovered site not readable for new transactions" case. Keep the DM `readable` flag for `querystate` display only.
- **Replicated read with no qualifying site → abort, not wait** (Tests 23 and 24). The FAQ says "wait" for a similar scenario, but that answer is for the locking variant.
- **Garbage collection: skip it.** Test 22 needs T1 to stay in the graph after T3 begins, even though T1 and T3 don't overlap. The test scripts are small.
- **Available Copies abort can happen at `end` or right at `fail`** (Test 4 says both are correct). Keep doing it at `end`.

## Still open (ask TA)

1. **Test 2's comment versus our cycle rule.** T2 has only `T2 -rw-> T1` edges, with no edge back to T2, so under the cycle rule T2 **commits**. The comment says SSI causes an abort. The dump is the same either way. Ask which outcome the graders expect for T2.
2. **Does a site failing after T *read* from it abort T?** The FAQ says yes, but that is the locking variant. Proposal §4.3.5 says no under SSI, and no SSI test exercises it. Current choice: no.
3. **Write when every site holding the variable is down:** the tests and FAQ don't cover it. Current choice: wait.
4. **Output format:** the tests only describe dumps in prose. The FAQ says showing which transaction did each read is "helpful", for example `T2 reads x3: 30`. Choose one exact format and use it everywhere.
