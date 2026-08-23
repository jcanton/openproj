# Making CI faster

*Written 2026-08-23, on branch `ci-speed` (PR #72). Two runs, both green:*

| run | tree | pytest | job |
|---|---|---:|---:|
| [32631287159](https://github.com/jcanton/openproj/actions/runs/32631287159) | `main` + the `--durations` flags | 1392.75s | 23m24s |
| [32633361097](https://github.com/jcanton/openproj/actions/runs/32633361097) | + changes 1 and 2 below | **711.04s** | **12m08s** |

*Raw tables in `docs/probes/ci-durations.txt` and
`docs/probes/ci-durations-after-cache.txt`. The first two changes are already
made and already measured; changes 3 to 9 are not written.*

jcanton asked: *"we should make testing and CI faster: splitting it as much as it
makes sense to run tests in parallel instead of sequentially?"* — with the weight
on **as much as it makes sense**. A suite that halves its wall clock and stays
deterministic is a better answer than one that quarters it and goes intermittent,
because a gate that is red for reasons nobody can reproduce teaches everybody to
read past red, and that is the one failure a gate must never have.

The short answer is that the question had the wrong premise, and the measurement
says so. **Most of the twenty-two minutes was not parallelism-shaped at all.** It
was one line of `render.py` recompiling the same fourteen Jinja templates,
several times per record, on every page the suite drew. Fixing that is seventeen
lines of code with no concurrency in any of them, and it took the suite from
23m24s to **12m08s** — half the gate, measured on CI, before anything ran beside
anything else.

Splitting comes after, and when it comes it should split across **machines**, not
across processes on one machine — for reasons that are measured below and are not
the reasons anybody guessed. The runner was probed in the same run and it is a
**2-core, 8 GB** box, which settles that argument rather than assuming it.

---

## 1. What CI costs today, per step, measured

From the jobs API for run 32631287159, one job named `check` on `ubuntu-latest`:

| Step | Seconds |
|---|---:|
| Set up job | 1 |
| `actions/checkout@v7` | 1 |
| `astral-sh/setup-uv@v10.0.1` | 2 |
| `actions/setup-node@v7` | 1 |
| `uv sync --locked --group dev` | 0 |
| `uv run ruff check .` | 0 |
| **`uv run pytest -q`** | **1395** |
| post steps + complete job | 0 |
| **job total** | **1404** |

The same eight steps in the second run: 1, 1, 3, 0, 1, 0, **713**, 1. Nine
seconds either way.

And the box itself, from a one-line probe in the second run — because how much
parallelism to buy depends on it and this repository is private:

```
nproc            2
free -m          Mem: 7942 total, 6821 available   Swap: 3071
df -h /dev/shm   tmpfs 3.9G
google-chrome    151.0.7922.137
```

**Two cores and eight gigabytes.** GitHub's standard `ubuntu-latest` is
4-core/16 GB for public repositories and this is not one, so `-n auto` here means
`-n 2` and a hard-coded `-n 4` would twice-oversubscribe the CPU. Memory and
`/dev/shm` are not constraints at any width worth trying.

**Nine seconds of the twenty-three minutes is not pytest.** The uv cache is warm,
the lockfile resolves instantly, `setup-node` is a cached tarball, and Chrome is
already in the image. Two theories die here:

* *"ruff runs serially in front of a twenty-minute suite."* It runs in **0
  seconds**. Moving it out of the critical path is worth zero seconds of wall
  clock. It is still worth doing, for a different reason — see change 7.
* *"Extra jobs would pay ninety seconds of setup each."* They would pay **nine**.
  That single number is what decides splitting-by-job against splitting-by-
  process, and it is the opposite of what it was assumed to be.

There is nothing to win outside the one pytest step. Every change below is
inside it, or is about how many machines run it.

## 2. What the suite costs, per category, measured

`--durations=0 --durations-min=0.05` over the full run, in
`docs/probes/ci-durations.txt`. 1107 rows summing to **1365.28s** of the
1392.75s, so only ~27 seconds is collection, imports and the 3954 hidden
sub-50ms durations. Everything below is summed out of that file directly.

By phase: **setup 519.23s, call 825.22s, teardown 20.83s.** Forty per cent of the
measured suite runs before any test body does. Any plan that only makes test
bodies faster is arguing about 60% of the problem.

By machinery, each test charged to its single most expensive one — Chrome beats
node beats hypothesis beats git beats plain Python:

| category | seconds | tests |
|---|---:|---:|
| Chrome, one process per assertion | 555.88 | 175 |
| pure Python | 439.41 | 274 |
| a real bare git repo | 218.01 | 287 |
| node driving shipped JS | 61.19 | 93 |
| Chrome, one long-lived process | 6.84 | 3 |
| hypothesis | 3.78 | 4 |

That classification covers 1285.11s of the 1365.28s — it was built by static
reachability from each test body and its fixtures, and it silently dropped 55
rows worth 80.17s, almost all of them `test_gitdoor.py`. **Use it for
proportions and the per-file table below for decisions.** A per-file summary made
any way other than summing the file disagrees with it: one earlier pass had
`test_gitdoor.py` at 4.19s over 10 tests where the table holds 43 rows summing to
47.53s, and had `test_coedit.py` at 87.91s with its 20.58s of teardown dropped.
These are the numbers the shard cut has to be made from:

| file | total | setup | call | teardown | rows |
|---|---:|---:|---:|---:|---:|
| `test_render.py` | 367.71 | 246.18 | 121.53 | 0 | 177 |
| `test_injection.py` | 226.11 | 218.14 | 7.97 | 0 | 26 |
| `test_editor.py` | 178.42 | 4.36 | 174.06 | 0 | 118 |
| `test_coedit.py` | 115.47 | 0.64 | 94.25 | 20.58 | 66 |
| `test_table.py` | 69.44 | 15.33 | 54.11 | 0 | 203 |
| `test_facets.py` | 54.10 | 2.13 | 51.97 | 0 | 42 |
| `test_gitdoor.py` | 47.53 | 0 | 47.53 | 0 | 43 |
| `test_graph_layout.py` | 46.46 | 20.82 | 25.64 | 0 | 16 |
| `test_cascade.py` | 39.79 | 12.76 | 27.03 | 0 | 69 |
| `test_card.py` | 35.65 | 0.98 | 34.67 | 0 | 28 |
| `test_search.py` | 27.72 | 1.69 | 26.03 | 0 | 26 |
| `test_hill.py` | 22.35 | 0.77 | 21.58 | 0 | 25 |
| `test_seats.py` | 21.42 | 0.64 | 20.78 | 0 | 18 |
| `test_web.py` | 19.16 | 0.69 | 18.22 | 0.25 | 88 |
| the other 20 files | 93.95 | | | | 162 |
| **total** | **1365.28** | **519.23** | **825.22** | **20.83** | **1107** |

Cost has nothing to do with test count. `tests/test_table.py` is 203 rows for
69.44s; `tests/test_injection.py` is 26 rows for 226.11s. `tests/test_store.py`
and `tests/test_remote.py` — the two heaviest git-touching files by source volume
— do not appear in the table at all, meaning every one of their tests is under
50ms.

Two files that nobody named are pure rendering and nothing else, and they went
the same way as the injection fixtures.
`test_gitdoor.py::test_a_file_nobody_could_parse_costs_that_file_and_nothing_else`
is 21 parametrisations, each opening every route **twice** — once for the 200 and
once to read what the page says — which is ~460 page renders for 47.53s.
`test_web.py`'s 88 rows are 85 tests at ~0.22s each, which is what a real bare
repo per test actually costs, and it is cheap; the render on top of it was not.

### And the same table after changes 1 and 2

Same command, same tree plus seventeen lines. 732 rows summing to 675.79s of
711.04s — **setup 59.26s, call 600.60s, teardown 15.93s.** Setup was 519.23s;
460 seconds of it was compiling templates.

| file | before | after | Δ |
|---|---:|---:|---:|
| `test_render.py` | 367.71 | 95.60 | −272.11 |
| `test_injection.py` | 226.11 | 18.99 | −207.12 |
| `test_gitdoor.py` | 47.53 | 2.90 | −44.63 |
| `test_editor.py` | 178.42 | 151.27 | −27.15 |
| `test_table.py` | 69.44 | 43.28 | −26.16 |
| `test_cascade.py` | 39.79 | 16.40 | −23.39 |
| `test_facets.py` | 54.10 | 32.92 | −21.18 |
| `test_web.py` | 19.16 | 2.36 | −16.80 |
| `test_coedit.py` | 115.47 | 98.99 | −16.48 |
| `test_delete.py` | 16.92 | 12.60 | −4.32 |
| `test_card.py` | 35.65 | 32.67 | −2.98 |
| `test_graph_layout.py` | 46.46 | 45.79 | −0.67 |
| **suite** | **1392.75** | **711.04** | **−681.71** |

The shape of that column is the whole finding. Files that draw pages fell by
70–92%. Files that start Chrome processes or sleep on real clocks —
`test_graph_layout.py`, `test_card.py`, `test_editor.py`, `test_coedit.py` —
barely moved, and they are now the suite. **After one non-parallel change,
`test_editor.py` alone is 21% of what is left.**

### The thing under all of it

`tests/test_injection.py`'s two module-scoped fixtures cost 183.1s between them
— 13% of the entire run — with no Chrome and no node in either. They looked
inherently expensive: the marker corpus is 479 records, because `markers()`
derives the corpus from `render.py`'s source rather than listing it, and each
fixture builds a hostile corpus and a benign control.

Profiled, they were not. One `render_static` over that corpus was **43.6 seconds,
6,739 calls to `builtins.compile`, and 21 seconds inside `jinja2.visitor`**. The
work was not rendering. It was *compiling templates*:

```python
_ENV = Environment(autoescape=True)

def _fragment(template: str, **values: object) -> Markup:
    return Markup(_ENV.from_string(template).render(**values))
```

`Environment.from_string` compiles every time it is called. Jinja's cache hangs
off a loader and `get_template`, and there is no loader here because the fourteen
templates are string constants in `render.py`. Several of the call sites are per
record — the hill is a fragment, the promote menu is a fragment — so a page's
cost in template compilation was linear in the size of the plan.

Measured on this laptop, before and after a `functools.cache` on the compile:

| | before | after |
|---|---:|---:|
| `render_static`, 479-record marker corpus | 43.57s | 2.19s |
| `render_static`, frozen golden corpus | 0.66s | 0.027s |
| `render_detail` ×5, golden corpus | 2.70s | 0.085s |
| one served `GET /detail/{id}` | 60ms | 5ms |
| `test_a_bar_is_exactly…` (one test) | 13.5s | 0.42s |

This is not only test time. The deployed server draws every page through the same
calls, so a record page was paying a full lex-parse-codegen of the detail
template on every request.

### The Chrome shape

555.88s over 175 tests, ~3.2s each on the runner. `browser.py` spawns a fresh
`--headless=new` process per assertion and gives it
`--virtual-time-budget=SETTLE+patience` = 2500ms.

Probed directly on this laptop, five runs each, minimum reported:

| page | bytes | budget | wall clock |
|---|---:|---:|---:|
| blank, 36 bytes | 36 | 1 | **1.93s** |
| blank, 36 bytes | 36 | 2500 | 1.92s |
| blank, 36 bytes | 36 | 8000 | 1.94s |
| `render_table` | 540 KB | 2500 | 2.07s |
| `render_table` | 540 KB | 8000 | 2.03s |
| `render_graph` | 2.29 MB | 2500 | 2.21s |
| `render_graph` | 2.29 MB | 8000 | 2.24s |
| `render_detail` (Ace) | 418 KB | 2500 | 2.00s |
| `render_detail` (Ace) | 418 KB | 8000 | 2.01s |

Three facts fall out, and all three matter:

1. **A 36-byte page costs 1.93 seconds.** That is process startup and nothing
   else. Roughly 90% of every `measured_in` call is Chrome booting; the page
   under test is worth 70–310ms of it.
2. **`--virtual-time-budget` is a ceiling, not a sleep.** Raising it from 2500 to
   8000 costs nothing measurable on a settled page. So lowering it saves nothing
   — and raising it, which is the cheap fix for the pixel-comparison race
   `screenshot`'s docstring records, is free.
3. **Startup flags do not help.** Adding twelve of the usual quieting flags
   (`--no-first-run --disable-background-networking --disable-component-update
   --disable-sync --disable-extensions --disable-features=Translate,…`) moved the
   1.93s by less than the noise.

So the only levers on 175 Chrome launches are: run them at the same time, or
launch fewer of them. Nothing in between.

---

## 3. The changes, in order

Each is stated as what to do, what it is worth, and what it risks. The first two
are already on this branch as commit `d979881`; the rest are not written.

### 1. Compile each template once — `src/openproj/render.py` — **done**

Add `@cache def _compiled(source: str) -> Template: return _ENV.from_string(source)`
and route all thirteen `_ENV.from_string(...)` call sites through it. Key on the
source string: that is what the call sites have, the keys are module constants
that are already resident, and nothing builds a template string at run time, so
the cache cannot grow past fourteen entries.

**Worth: 681.71 seconds, measured on CI.** 1392.75s → 711.04s, 23m24s → 12m08s,
in one commit with no concurrency in it. Predicted eight to ten minutes; got
eleven and a half. `test_injection.py` went 226.11 → 18.99, `test_render.py`
367.71 → 95.60, `test_gitdoor.py` 47.53 → 2.90, and the suite's setup phase
519.23 → 59.26.

**Risk:** none found, and it was looked for rather than assumed. A cache that
changes one byte of a page is a worse bug than the one it fixes, so every page of
both corpora — the frozen golden one and the shipped `seed/` demo — was hashed
static and served, with the cache and without it: **30 outputs, byte-identical.**
Filters stay live because Jinja resolves them against the environment at render
time, not at compile time, so the `tojson` override still applies. Compiled
`Template` objects are stateless and re-renderable by design.

### 2. The timeline test's quadratic regex — `tests/test_render.py` — **done**

`test_a_bar_is_exactly_as_wide_as_the_span_the_scheduler_computed` was 30.03s on
CI, of which 13.4 of 13.6 laptop-seconds were inside one line:

```python
for rule in re.findall(r"([^{}]*)\{", style)
```

`[^{}]*` runs to the closing `}` of each declaration block, fails the `\{`, and
backtracks a character at a time from every start position inside the block —
quadratic in block length, over a 110 KB inlined stylesheet. Replaced with
`style.split("{")[:-1]` and `chunk.rsplit("}", 1)[-1]`, which is the same 318
strings in the same order in 0.1ms.

**Worth:** 30 seconds, 2.2% of the old gate, in one line. It is part of the
681.71s above; on this laptop the test went 13.5s to 0.42s including collection.
**Risk:** none. The assertion it feeds — that no selector may reach a bar without
naming what kind of element it is — is untouched, and the output was compared
element-for-element.

### 3. Bound uvicorn's shutdown in `serving` — `tests/test_coedit.py:2251`

Four real-socket room tests each pay a flat ~5.0s in **teardown** (5.09, 5.05,
5.02, 5.04 in the first run; 15.93s of the second run's 15.93s total teardown is
still the same three or four). A 5-second constant that identical across four
tests is a timeout being waited out, not work being done — most likely uvicorn
declining to finish shutting down while a connection the test deliberately
stalled is still open. It is now 2.2% of a much smaller suite.

Do not diagnose it; bound it. `uvicorn.Config(..., timeout_graceful_shutdown=1)`.
Every assertion in these tests happens before the fixture tears down, so a
shorter shutdown cannot change what they prove.

**Worth:** ~16 seconds. **Risk:** low; if the cause is something else the number
simply does not move, which is itself the diagnosis.

### 4. Give `serving` a port it actually holds — `tests/test_coedit.py:2251`

The fixture binds a probe socket to port 0, reads the number, **closes the
probe**, and hands the number to uvicorn. Between the close and uvicorn's bind
the port belongs to nobody.

This repository already has the correct pattern, at `tests/test_web.py:1476`:
`uvicorn.Config(app, host="127.0.0.1", port=0, …)`, wait for `server.started`,
then read the real port back off `server.servers[0].sockets[0].getsockname()[1]`.
The socket is never unbound, so there is no window. `tests/browser.py:216` does
the same thing a third way, with `--remote-debugging-port=0` and Chrome writing
the number it got into `DevToolsActivePort`.

**Worth:** zero seconds. It is here because it is a real latent bug, the fix is
five lines, and it is the one hazard that would bite immediately if anybody ever
does run two of these on one machine. Under the split recommended below it is not
a prerequisite — shards get their own machines, and within a shard the tests run
serially exactly as today.

`tests/test_cli.py:257`'s `free_port()` is the same TOCTOU and is nearly
harmless, because nothing ever binds the number: `run_demo` replaces
`cli._exit_aware_server`, so uvicorn never starts and the only consumer is
`cli._taken`'s pre-flight probe. Leave it, or monkeypatch `cli._taken` to
`lambda *a: False` and pass `--port 0`.

### 5. Clear `web._PARSED` before the two tests that assert on it — **prerequisite for 6**

`tests/test_web.py:3759` and `:3823` reach into `openproj.web._PARSED`, a
module-global parse cache that every earlier test in the same process has been
filling. `test_all_five_kinds_are_read_through_the_one_cache` asserts each of five
kind-directories appears among the cache's keys — leftovers can supply those keys,
so it can pass while the app under test caches nothing.
`test_nothing_edits_a_record_after_it_has_been_parsed` snapshots the whole cache,
other tests' entries included, and asserts `before` is non-empty.

Neither is flaky today. Both have a strictness that depends on what ran before
them, and **any** split — by job or by process — changes what that is. Add
`web._PARSED.clear()` immediately before `create_app(...)` at line 3818 and before
`client.get("/")` at line 3759, or an autouse fixture in `tests/conftest.py` that
clears it per test (which also removes the cross-test memory growth).

**Worth:** zero seconds. It makes two assertions mean what they say, independent
of shard layout.

### 6. Split CI into shards, keeping one job named `check`

This is the wall-clock change. Five test jobs plus a lint job and a gate, each a
full `actions/checkout`, differing only in the pytest selection argument.

**Why jobs and not `pytest-xdist`, in one paragraph:** the measured cost of a job
is nine seconds. Five test jobs is 45 extra seconds of machine time and gives
five machines — ten vCPU if the runner is the 2-core box a private repository
gets, twenty if it is the 4-core one. `-n 2` on one box gives two vCPU that
Chrome is already contending for. Sharding is roughly 5× the compute for 45
seconds; xdist is at best 1.5× on this hardware and it makes every wall-clock budget in
`test_coedit.py` and `test_web.py` share a CPU with somebody else's headless
Chrome. Within a shard the tests still run serially in one process, in file
order, on their own kernel — which is exactly the condition every port bind,
every `time.sleep(0.5)` and every `--virtual-time-budget` margin was measured
under. The full argument, and the four `--dist` modes, is in section 4.

**The break-even, stated:** with a suite of `T` seconds split `K` ways and a
per-job overhead of 9s, wall clock is `T/K + 9`. The `K`-th shard earns its place
while `T/(K·(K−1)) > 9`, i.e. while `K·(K−1) < T/9`. At `T ≈ 900s` that is
`K ≤ 10`. **Setup cost does not stop you before ten shards. Balance does.**

**Billed minutes go down, not up.** GitHub bills each job rounded up to the
minute. Today: one job, 24 minutes. Five shards of an 800-second suite, plus a
lint job and the gate: about 15. The template cache pays for the sharding several
times over.

**The blocker, and its zero-admin fix.** Branch protection on `main` requires
exactly one status check, `contexts: ["check"]`, with `enforce_admins: true`. A
`strategy.matrix` renames it to `check (browser)`, `check (python)`, …; separate
jobs remove it. GitHub does not fail a PR for a required context that no longer
exists in the way people expect — the PR sits pending, or, if the old name is
dropped from the required list without the new ones being added, **every shard
can be red and the merge button is green.** That is the sharding failure mode
that ships a bug rather than blocking one.

So do not rename it. Name the shards something else and add a fan-in job that
*is* `check`:

```yaml
jobs:
  suite:
    strategy:
      fail-fast: false
      matrix:
        shard: [editor, views, graph, coedit, web, model]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7            # full, never sparse — see below
      - uses: astral-sh/setup-uv@v10.0.1
        with: {python-version: "3.12", enable-cache: true}
      - uses: actions/setup-node@v7
        with: {node-version: "24"}
      - run: uv sync --locked --group dev
      - run: uv run pytest -q $(cat .github/shards/${{ matrix.shard }})

  check:                                     # the one required context
    needs: [suite, lint]
    if: '!cancelled()'
    runs-on: ubuntu-latest
    steps:
      - run: |
          [ "${{ needs.suite.result }}" = success ] || exit 1
          [ "${{ needs.lint.result }}" = success ] || exit 1
```

Three details in there are load-bearing:

* `needs.suite.result` on a matrix job is the aggregate — `success` only if every
  leg succeeded. A skipped or cancelled leg is not `success`, and the `[ … ]`
  test fails closed on both.
* `if: '!cancelled()'` and **not** `if: always()`. `always()` runs the gate even
  when the run is being cancelled, which is exactly what `concurrency:
  cancel-in-progress` does on every third push — and a gate that runs after its
  shards were cancelled reports a red required check on a run nobody was waiting
  for. `!cancelled()` runs it when a shard fails and skips it when the run is
  torn down.
* `fail-fast: false`, so one red shard does not cancel the other five and hide
  four more failures. The whole point of a four-minute gate is getting all the
  bad news in one pass.

The shard file lists live in `.github/shards/<name>` as plain space-separated
paths rather than inline in the matrix, because change 8 has to read them from a
test.

**Never a sparse checkout.** 27 of the 47 files in `tests/` import from another file in `tests/` —
`test_socket_offer.py` imports `test_web` and `test_store`; `test_editor.py`
imports `test_web`, `test_store`, `test_injection`, `pages`, `browser`;
`tests/test_remote.py:375` requests the `preempted` *fixture* from `test_store`
by name. A shard missing an import hub fails at collection, not at assertion.
Every shard is a full checkout and differs only in the selection argument.

**Where to cut.** From `docs/probes/ci-durations-after-cache.txt`, not from the
pre-cache table — the cache moved the boundaries by more than the shard sizes.
The suite is 675.79s of attributed rows and the five legs balance to within 8%:

| shard | files | measured |
|---|---|---:|
| `editor` | `test_editor.py` | **151.3s** |
| `views` | `test_render.py`, `test_table.py` | 138.9s |
| `graph` | `test_graph_layout.py`, `test_card.py`, `test_facets.py`, `test_hill.py` | 131.2s |
| `coedit` | `test_coedit.py`, `test_socket_offer.py`, `test_search.py` | 126.1s |
| `rest` | `test_seats.py`, `test_injection.py`, `test_cascade.py`, `test_edges.py`, `test_delete.py`, `test_deck.py`, `test_themes.py`, `test_payload.py`, `test_status_gate.py`, `test_gitdoor.py`, `test_web.py`, `test_writes.py`, `test_records.py`, `test_cli.py`, `test_schedule.py`, `test_notes.py`, `test_index.py`, `test_headers.py`, `test_issues.py`, `test_exclusion.py`, `test_product.py`, `test_credential.py`, `test_identity.py`, `test_validate.py`, `test_model.py`, `test_parse.py`, `test_store.py`, `test_remote.py`, `test_config.py`, `test_auth.py`, `test_harness.py` | ~128s |

**Five, and five is the ceiling.** The break-even formula allows ten, but
`test_editor.py` is 151.3s on its own and no file-level scheme goes below it. A
sixth shard would split one of the four ~130s legs and change the critical path
by nothing at all. Past 151 seconds the only lever left is splitting that file,
and its natural internal seam is `?editor=ace` against `?editor=plain`.

If five jobs feels like too many for a repository this size, four is nearly as
good: fold `coedit` into `rest` and give `test_search.py` to `views`, and the
critical path is ~180s instead of ~151s. Six is strictly worse than five.

`test_editor.py` is the file that has to be alone, and the post-cache table is
why: 151.27s of which 151.04s is `call`, 115 tests, and 53 of the suite's 135
`measured_in` call sites — every one of them a real Chrome laying out a page
carrying 594 KB of inlined Ace. It is 21% of the suite and none of it is
rendering.

`coedit` is a shard for the opposite reason: it is the only one with real
sockets, real uvicorn and real wall-clock budgets, and it must **not** be
internally parallelised or reordered. Its own machine is how that stays true for
free.

**Worth:** the critical path becomes the largest shard. 151s + 9s of setup +
a few seconds of collection ≈ **2m45s** of job time, against 12m08s now and
23m24s before this branch; three to five minutes by the clock on the wall once
the runner queue is counted. Queue time is not ours and should not be promised.

**Risk:** the branch-protection failure above (closed by the `check` fan-in), a
test file that lands in no shard (closed by change 8), and the `_PARSED`
assertions (closed by change 5). Five machines instead of one is five
independent chances of a runner-level hiccup; a re-run is one click and four
minutes rather than twenty-three. Each shard pays `render.py`'s `@cache` reads —
594 KB of Ace (`ace.js` + `keybinding-vim.js`), 1.98 MB of graph libraries
(`cytoscape.min.js` + `elk.bundled.js`) — once in its own process, so five times
instead of once; that is sub-second, and it is the honest cost of the split.

### 7. `ruff` in its own job

A `lint` job: checkout, setup-uv, `uv run ruff check .`. About 25 seconds.

**Worth: zero seconds of wall clock on a green run.** Say that plainly, because
the theory it comes from — "ruff sits serially in front of twenty minutes" — is
measured at 0s and is false. What it buys is feedback latency on a *red* run: a
misplaced import is reported in 25 seconds instead of after the whole suite.
Since the fan-in `check` job exists anyway, adding `lint` beside the shards is
free.

Do **not** make the shards `needs: [lint]`. A lint error and a test failure are
different questions and you want both answers from one push; putting lint in
front trades 25 seconds of every green run for machine time on runs that were
going to be re-pushed regardless.

### 8. A test that holds the shard lists against `tests/`

The shard lists are a hand-written list of files, and a hand-written list fails
**open**: add `tests/test_new_thing.py`, forget the list, and it runs nowhere
while CI stays green. That is green-for-the-wrong-reason, which this repository
already closes elsewhere — `test_every_html_get_route_is_in_the_census` holds the
census against `app.routes`, and `test_harness.py:46` scans every `tests/test_*.py`
off disk.

Write the same shape: read the shard files, glob `tests/test_*.py`, and assert
every file appears in exactly one shard and every named file exists. It fails on
the commit that adds the file, not six weeks later.

**Worth:** zero seconds, and it is the difference between sharding being safe and
sharding being a slow leak.

### 9. Take the measurement flags back out

`--durations=0 --durations-min=0.05` and the `nproc && free -m && df -h /dev/shm`
probe are on this branch as measurement, not as policy. Both tables have now been
read and the shard boundaries in change 6 are cut from the second one, so both
lines have done their job and should come out in the commit that lands change 6
— or sooner. The durations bookkeeping is not free: the first measured run was
23m12s against 21m27s–22m23s for the six runs before it, so treat the absolute
numbers as ±5% and the proportions as solid.

Keep the two probe files. `docs/probes/ci-durations.txt` and
`docs/probes/ci-durations-after-cache.txt` are what the shard lists are cut from,
and what the next person re-cuts them from when the suite has grown.

---

## 4. Considered and rejected

### `pytest-xdist`, in any `--dist` mode — rejected

Not because it does not work, but because sharding by job is strictly better here
and stacking both makes eight hazards live for a marginal gain.

* **The box is the argument, and it was measured rather than assumed.** `nproc`
  on the runner reports **2**, with 7942 MB of RAM and a 3.9 G `/dev/shm`. This
  repository is private, and GitHub's standard `ubuntu-latest` is 4-core/16 GB
  only for public ones. So `-n auto` (`os.cpu_count()`) means `-n 2` here, and
  `-n 4` written on the public number would 2×-oversubscribe the CPU — which is
  precisely what breaks the wall-clock tests below.
* **The Chrome bucket does not parallelise as well as its shape suggests.** 90%
  of a `measured_in` call is process startup, which is CPU- and IO-bound and uses
  more than one core on its own. Two headless Chromes on two vCPUs are not two
  Chromes' worth of throughput. Realistic ceiling on this hardware: 1.4–1.7×.
* **Memory is not the blocker, for the record.** Two pytest workers (~300–400 MB
  each once `render.py`'s caches hold 594 KB of Ace and 1.98 MB of graph
  libraries) plus two headless Chromes (~400–700 MB each across browser, gpu and
  renderer processes) is ~2.5 GB against 7. At four workers it is ~4.5 GB —
  survivable, with the page cache gone.
* **What it would cost first.** `pytest-xdist` is not in the dev group and CI
  runs `uv sync --locked`, so adding `-n` without adding the plugin and
  committing a regenerated `uv.lock` gives a red CI on the *sync* step. Then:
  `tests/test_coedit.py:2251`'s probe-socket port becomes a real collision;
  `tests/test_web.py:3736` asserts a reader waits under 300 ms while a
  monkeypatched 0.6s write runs, and 300 ms is an ordinary GET on a contended
  box, so it fails accusing the code of a defect it does not have;
  `tests/test_coedit.py:2316`'s `STALL_SECONDS = 0.2` / `sleep(0.4)` window is a
  2× margin against a starved event loop; the four real-socket room tests
  (`tests/test_coedit.py:2499` onward) are a chain of literal
  `sleep(0.5)/1/2/3`; and `screenshot`'s own docstring records that its PNG byte
  comparison already raced on CI once at a 2500ms budget, so halving each
  Chrome's CPU halves a margin that has already been too small.

  All of those are fixable — widen the ratios rather than the absolutes, pin the
  real-socket tests with `@pytest.mark.xdist_group("realtime")`. But it is six
  test-code changes and a lockfile change to buy less than sharding buys with
  one workflow file.

* **And the arithmetic no longer favours it.** `-n 2` at a 1.5× real ceiling
  takes 711s to ~475s. Five shards take it to ~151s. The two are not close, and
  only one of them puts a headless Chrome and a 300-millisecond latency
  assertion on the same two cores.

* **If it is ever used anyway, the mode is `--dist loadfile`.** Argued against
  the alternatives:
  * `load` — fastest scheduler, splits by test. It re-runs every module-scoped
    fixture on every worker that draws one of its tests. The five module-scoped
    fixtures here (`pem`, `marker_static`, `marker_served`, `pages`,
    `broken_id_table`) are merely *wasteful* under it and never wrong — each
    builds into a per-worker temp dir and returns strings tests only read — but
    it also scatters `test_coedit.py`'s real-socket block across workers, which
    is the one thing that must not happen.
  * `loadfile` — whole file to one worker. Module-scoped fixtures are built once
    each, `test_coedit.py` stays entire on one worker in its recorded order for
    free, and the balance cost is acceptable because the file sizes are already
    known from the durations table. This is the one.
  * `loadgroup` — `load` plus honouring `@pytest.mark.xdist_group`. It gives back
    what `load` takes away, but only for the tests somebody remembered to mark,
    and it fails open when somebody adds an unmarked timing test.
  * `worksteal` — best balance, worst determinism: which worker runs which test
    changes between runs, so a flake reproduces on a different worker each time.
    Wrong trade for a suite whose expensive tests are the timing-sensitive ones.

### Sharding by sparse checkout — rejected

27 files in `tests/` import from another file in `tests/`, and `tests/test_remote.py:375`
requests a fixture from `test_store` by name. A shard missing
`tests/test_web.py`, `test_store.py`, `test_injection.py`, `test_index.py`,
`browser.py`, `pages.py`, `cascade.py`, `plans.py` or `wsclient.py` fails at
collection. Full checkout, always; only the selection argument differs.

### Lowering `--virtual-time-budget` — rejected, with the measurement

It is a ceiling, not a sleep. 2500 and 8000 cost the same wall clock on a settled
page (2.03s vs 2.07s for the table; 2.21s vs 2.24s for the graph). There is
nothing to reclaim, and the 5000 in `screenshot` was raised from 2500 for a
reason that is written down: the byte comparison in
`test_the_frozen_edge_is_a_pixel_a_browser_draws` caught a page mid-settle on CI
while passing locally. The corollary is the useful half — **raising it is free**,
so if the four PNG comparisons ever race again, raise to 8000 and pay nothing.

### Chrome startup flags — rejected, with the measurement

Twelve of the usual quieting flags moved a 1.93s blank-page launch by less than
the run-to-run noise. Startup is startup.

### Caching anything else — rejected

`enable-cache: true` is already on setup-uv and `uv sync --locked` measures 0s.
`setup-node` is 1s. Chrome ships in the image. That is the whole nine seconds.
Two specific ideas, both refused:

* **A warmed Chrome profile.** The 1.93s is process startup, not profile
  creation, and `--headless=new` in command mode (`--screenshot`,
  `--print-to-pdf`, `--dump-dom`) takes a throwaway profile anyway — which is
  also why concurrent invocations do not contend over a `SingletonLock`, verified
  by running four at once and getting four byte-identical PNGs.
* **The hypothesis example database.** It is 3.78s of the suite, `.hypothesis/`
  is not cached between runs today, and caching it across shards would make one
  shard's failure reproducible only in that shard. Leave it. (`.hypothesis/` and
  `.pytest_cache/` are missing from `.gitignore`, which is untidy and not a
  hazard.)

### Rescoping `test_render.py`'s `rendered` / `seed_index` fixtures — rejected

This looked like the single best one-line change in the suite: 127 setup rows in
a flat 1.5–3.0s band, 243.2s in total, all of them `load_repo` + `build_index` +
`render_static` over the frozen corpus, run once per test because both fixtures
are function-scoped. Promoting them to session scope looked worth four minutes.

It was worth four minutes of *template compilation*. With change 1 in, the whole
`rendered` fixture is `load_repo` 0.015s + `build_index` 0.001s + `render_static`
0.026s = **0.042s** on this laptop, and CI agrees: `test_render.py`'s setup went
246.18s to **15.72s** without one fixture changing scope. Rescoping now buys at
most ten of those remaining seconds, in exchange for 109 tests sharing one
mutable directory and a `tmp_path` → `tmp_path_factory` conversion. Not worth it.

Recorded because the reasoning is the expensive half: the measurement that made
it look like a four-minute win was measuring something else, and a plan that
acted on it would have shipped a shared-state hazard and kept the real cost.

The same correction applies to `test_injection.py`'s two module fixtures. They
are *already* module-scoped; the plan to stop building the hostile and benign
corpora twice was aimed at 183 seconds that were template compilation, not corpus
construction — the file is 18.99s now with both corpora still built twice, so
there was never 183 seconds there to take. The benign control is what makes
`assert_same_shape` mean anything. Keep both corpora.

### One shared Chrome for all 175 pixel tests — deferred, not rejected

This is now the largest remaining item by a distance, and the post-cache table
makes the case louder than the pre-cache one did: with rendering gone, 600.60 of
the suite's 675.79s is `call`, and the top of that column is
`test_editor.py` (151.27s), `test_coedit.py` (98.99s), `test_render.py`'s Chrome
half (79.88s), `test_graph_layout.py` (45.79s) and `test_table.py` (43.28s). At
1.93s of process start per `measured_in` call and 175 such tests, **something
like 330 of those 600 seconds is Chrome booting.** `in_a_live_page` already keeps a long-lived browser and drives it
over DevTools, so the machinery exists — and, notably, the cheap path is the one
almost nobody uses: 3 tests and 6.84s.

Every command-line behaviour `measured_in` relies on has a DevTools equivalent:
`--window-size` → `Emulation.setDeviceMetricsOverride`, `--hide-scrollbars` →
`Emulation.setScrollbarsHidden`, `--force-prefers-reduced-motion` →
`Emulation.setEmulatedMedia`, `--virtual-time-budget` →
`Emulation.setVirtualTimePolicy` with `virtualTimeBudgetExpired`.

It is deferred because *equivalent* is a claim, and the failure mode is silent:
a viewport override is not an OS window, and the suite's most load-bearing test
is literally named *the box each view fills stops where the window does*. A
harness that measures something subtly different and still passes is the exact
green-looking red `browser.py` was written to prevent.

So the acceptance test comes first, and it is cheap: keep both harnesses behind a
switch, run the whole suite twice, and diff the JSON every `measured_in` call
returns. Byte-identical over all 135 call sites, or it does not land. After
change 6 the wall clock is already under three minutes, so there is no hurry —
this is a QUEUE item, sized at ~330s and gated on that diff. It is also the only
thing that gets `test_editor.py` under its 151-second floor without splitting the
file.

---

## 5. The honest expected end state

Two rows of this are measured and the rest is arithmetic over a measured table.

| after | pytest | job |
|---|---:|---:|
| before this branch | 1392.75s | **23m24s** |
| + changes 1 and 2 — **measured, green** | **711.04s** | **12m08s** |
| + change 3 | ~695s | ~11m50s |
| + change 6, five shards | ~151s critical path | **~2m45s** |

**Twenty-three minutes is already twelve, and five machines take it to about
three.** The last row is the largest shard (`test_editor.py`, 151.27s in the
run above) plus nine seconds of setup plus a few seconds of collection, plus
whatever the runner queue costs that morning; call it three to five minutes
honestly, because queue time is not ours to promise.

Note what the first row is worth on its own: **half the gate, from a change with
no concurrency in it, that also makes the deployed server draw every page
faster.** That is the answer to "should we parallelise" — parallelise second.

Billed machine time falls too, which is the part nobody expects of a parallel
build: GitHub bills each job rounded up to the minute, so before this branch it
was one job at 24 minutes, it is now one at 13, and the end state is five shards
plus a lint job plus a gate at about **12**. The template cache pays for the
sharding several times over, and the sharded gate is cheaper than the serial one
was.

**And here is what is now flaky that was not: nothing — provided changes 5 and 8
land with change 6.**

That is a real claim and it is the reason for the shape of this plan. Under
job-sharding, each shard runs its tests **serially, in one process, in file
order, on its own kernel**. Every port bind is uncontended exactly as it is
today. Every `time.sleep(0.5)` in `test_coedit.py` has the whole box. Every
`--virtual-time-budget` margin is measured against the same CPU it was sized
against. No test's neighbours change except by moving whole files, and no test in
this suite depends on a neighbour — verified: no `os.chdir` anywhere in `tests/`
or `src/`, no autouse fixtures, no ordering plugins, every `monkeypatch` is
function-scoped and restored, `coedit.Rooms()` is constructed inside
`create_app` rather than at module level, every `Store` and `create_app` in the
suite builds under `tmp_path`, and `render.py`'s `@cache`s are pure functions of
committed files.

The two exceptions are exactly changes 5 and 8, and neither is a timing problem:
the `_PARSED` assertions get weaker or stronger depending on what ran before
them, and a hand-written shard list fails open. Both are closed by construction
rather than by hoping.

What genuinely gets worse: five runners instead of one is five chances of an
infrastructure hiccup, and the shard lists need re-balancing when the suite grows
— which the durations table already tells you how to do, and which costs four
minutes to verify instead of twenty-three.

The path that was **not** taken, and why, in one line: `-n auto` would have put
two headless Chromes and a 300-millisecond latency assertion on the same two
vCPUs, and the first intermittent red would have been a test accusing the
co-editing code of a defect it does not have.
