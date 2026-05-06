# cascade.scripts

Operational scripts shipped with the package. Each module is invokable as
`python -m cascade.scripts.<name>` and exposes a small CLI.

## Files

```
scripts/
├── __init__.py
├── demo_data.py     Plain-Python definitions of the demo dataset
└── seed_demo.py     Idempotent orchestrator + CLI
```

## Demo seed

Seeds (or refreshes) a complete demo dataset so a reviewer cloning the repo
sees content end-to-end on first run:

- 1 demo team (slug `demo-team`)
- 2 users (manager and contributor)
- 3 OKRs across two quarters (one closed, two active including a higher-risk one)
- 8 decisions covering commits, target changes, descopes, replacements,
  closures, and a risk intervention
- 3 organizational learnings spanning alignment, estimation, and process

```bash
make demo                  # idempotent — skips if already seeded
make demo-reset            # wipe demo data and refresh
```

Or invoke directly:

```bash
python -m cascade.scripts.seed_demo --verbose
python -m cascade.scripts.seed_demo --reset --verbose
```

The script prints the demo team's UUID — paste it into the operator console
sidebar at `http://localhost:8501`.

### Idempotency

The seed looks up the demo team by its fixed slug (`demo-team`) before doing
anything. Two paths:

- **Team doesn't exist** → create everything from scratch
- **Team exists, no `--reset`** → skip the run with a one-line message
- **Team exists, `--reset`** → wipe the demo team's rows (scoped strictly
  to its team_id) and re-seed

The wipe is scoped to the demo team only; running `--reset` on a database
with non-demo teams does not touch any of their data. `tests/integration/
test_seed_demo.py::test_reset_does_not_touch_non_demo_data` guards this.

### Why slug-based, not UUID-based

The demo team's UUID is generated on first create. We need a stable
identifier across runs, and a human-readable slug doubles as something a
reviewer can paste into the operator console — `demo-team` is more
memorable than `c4f8a1e2-...`.

### Why declared as data, not generated

`demo_data.py` is plain Python data classes. The orchestrator walks them
and calls the repositories. The alternative — generating realistic-looking
content algorithmically — produces output that looks like a benchmark, not
like a real OKR. Reviewers reading the demo data are reading what cascade
is *for*: the OKRs are written in the voice of a real team, the decisions
show alternatives-considered reasoning, the learnings reference patterns
that recurred. Keeping them readable matters more than keeping them short.

### Adding to the demo

Edit `cascade/scripts/demo_data.py`. The unit tests in
`tests/unit/test_demo_data.py` enforce internal consistency — they'll fail
loudly if you add a decision pointing at an OKR that doesn't exist, an OKR
owned by a user that wasn't seeded, or KR weights that don't sum to 1.0.
Run `make test-unit` after editing.

## Testing

- `tests/unit/test_demo_data.py` — referential integrity of the demo data
- `tests/integration/test_seed_demo.py` — orchestrator end-to-end:
  first-run counts, slug lookup, decision references, double-run
  idempotency, refresh-with-reset, non-demo data preservation, content
  smoke check (no Lorem ipsum)
