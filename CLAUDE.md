# CLAUDE.md

@AGENTS.md

All project rules live in `AGENTS.md` (imported above), so every agent works from the
same rules. Change shared rules there, not here. This file only adds notes for Claude.

## Claude-specific notes

- Work usually comes through the "PROJECT R80" Claude project (threads plus shared memory).
  Save lasting decisions from Alex in project memory, and update `AGENTS.md` when a
  decision changes a repo rule.
- Two kinds of sessions:
  - **Cloud sessions** have this repo but no BoAt, no vcan and no display. There you can
    run `py_compile`, `make_dbc.py`, `r80_can_sim.py --log` and
    `hu-mockup/run.py --screenshots` (after the apt packages in AGENTS.md section 3).
    You cannot run `hu-virtual.sh`; say so instead of claiming the BoAt tests pass.
  - **Remote Control sessions** run on Alex's PC (`~/Project_R80`, BoAt at
    `/home/testuser/BoAt`). Use them for anything that needs BoAt, vcan or a real window.
- The cloud GitHub token cannot delete remote branches. Branch cleanup happens from
  Alex's device.
- Even if a session is told to develop on a `claude/*` branch, Alex's rule wins:
  commit and push to `master` (AGENTS.md section 4), unless Alex asks for a PR.
- When you show UI changes to Alex, render screenshots and attach them.
