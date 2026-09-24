# Game generation handoff

## Current feature

Branch: `feature/games-from-prompt`.

The user will test by browsing the normal BeePlay app and generating games themselves.
Use a separate worktree, its own ignored `.env`, database and game directories.
Do not create a separate test app or automatically submit five paid generations.

Implemented in this branch:

- Prompt version 2 assigns a stable, approximately 50/50 2D/3D preference from
  each generation's UUID. An explicit user dimension preference takes priority
  in the prompt. The assignment remains stable across provider-key retries.
- 3D currently means world-space geometry projected onto Canvas 2D, with no
  external engine or CDN. This is prompt guidance, not a verified rendering result.
- Node.js compiles generated inline scripts and event handlers without executing
  them. Invalid syntax is rejected before a draft becomes ready. Node is now a
  server dependency; release preflight checks it before changing the app.
- Preview error/timeout events invalidate publishing. A later load event cannot
  clear the failure until a new preview starts. The browser preserves report order
  and ignores stale load callbacks from a previous iframe.
- `tools/set-local-key.py` prompts without echo and updates only this worktree's
  ignored `.env`, preserving other settings and setting mode 0600.

Local startup:

```bash
uv sync --frozen
uv run python tools/set-local-key.py
./deploy/local.sh
```

Open `http://127.0.0.1:8021/create`. A key must be supplied on the destination
machine; no keys or local databases are committed. Node.js must be installed.
Use `BEEPLAY_LOCAL_PORT=8023 ./deploy/local.sh` if the default port is occupied.

Validation: 160 tests passed with `uv run --frozen python -m unittest discover -s tests`.
The key helper was separately checked with a temporary dummy key, including quotes,
backslashes, preservation of other settings and file permissions. No paid requests
were submitted for those tests. The feature has not been deployed to production.
The one-character repair of an existing production robot arm draft was a separate
operation, not a deployment of these changes.

## Incident behind the changes

The robot arm generation started on 2026-09-24 at 11:14:24 Asia/Shanghai, took
66 seconds and returned 4,735 completion tokens. Both preview attempts reported
errors. The generated code contained `o.22` instead of `0.22`, preventing the game
script from parsing. Old validation checked HTML structure only. A page load
signal could also overwrite the preview error and incorrectly enable publishing.

Remaining limits: syntax validation does not execute the game, test browser API
compatibility, verify rendering, or prove gameplay correctness. Preview events are
client reports, not a trusted quality assessment. No automatic repair loop or
browser smoke-test stage has been implemented. Generation preview failures were
also absent from the UX report during this investigation; that reporting gap has
not been addressed by this patch.

## Next direction requested by the user

The user wants approximately ten seconds per game and proposed parallelizing N
model requests under a specified contract to preserve complexity while making each
request fast. The following was the assistant's last response. It is a proposal,
not an approved architecture or an implemented change. The final product question
has not yet been answered.

---

**Feasible, but parallel requests only help if we change what the model generates.** Splitting arbitrary game code across agents would probably introduce more integration failures than it saves in time.

Our robot arm request took **66 seconds for 4,735 output tokens**. A ten-second target calls for much smaller outputs and less generated infrastructure.

I’d build it this way:

1. **Ship a tested game runtime** with rendering, touch controls, physics, scoring, restart and error reporting.
2. **Have the model produce a compact game specification**: objects, rules, goals, difficulty and visual parameters.
3. **Generate independent extras in parallel**, such as level layouts, dialogue or decoration. They shouldn’t block the first playable game.
4. **Validate the specification against a strict schema**, then run it using the existing runtime.

The contract is the crucial part. For example, a robot arm game would select an existing arm mechanic and specify object shapes, target positions, time limits and scoring. It would not generate its own renderer or input handling.

Your parallel-code proposal has two practical limits:

- Completion time is approximately **the slowest required request + assembly + validation**, not total time divided by request count.
- Separate requests can disagree about state, coordinates and lifecycle. A shared contract helps, but integrating arbitrary code still costs time.

**My recommendation: target ten seconds for a playable first version within supported game families.** Keep unrestricted custom generation as a slower path. Both 2D and 3D can use this architecture, but each needs a prepared runtime.

Before committing, measure time to first token and output speed on small specifications using your actual provider. Ten seconds is a useful target; we don’t yet have evidence that it’s a reliable guarantee.

The product decision is: **would you accept more constrained mechanics in exchange for fast generation and substantially fewer broken games?**
