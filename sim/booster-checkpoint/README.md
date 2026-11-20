# Booster K1 3v3 simulation checkpoint utilities

These are standalone Python 3.11+ checks and a portable resume convention. There are no agents, policies, simulator binaries, raw traces or credentials in this directory. Use separately authorized official inputs and a runner already installed on the execution machine.

1. Put the exact agent, opponent, scene and simulator version or digest into a private input inventory. Use `verify_agent_artifact.py PACKAGE.agent --pin SHA256 --id ID` to validate the local K1/x86_64 manifest and match bytes. This does not verify a signature or replace a Studio import test.
2. Run each attempt under a host-local exclusive lock with a new output directory. Preserve completed and interrupted attempts separately. Do not restart a live attempt, merge clocks across attempts, modify the opponent, or reuse a partial match as a result.
3. Use `checkpoint.py RUN_DIR` to emit a compact path-free checkpoint after the run. Keep original results and logs privately. Use `audit_official_replay.py RUN_DIR` to validate complete K1 visual replay. Replay timestamps are relative, and visual frames do not prove complete ball-contact history.
4. After an executor reset, pull the checkpoint branch, recover the authorized private inputs, compare digests, and check whether a valid final result already exists. If not, start a new attempt and carry forward the code/configuration, not the in-memory match state.

A short run is a diagnostic, even if it ends normally. Only the official referee-confirmed regulation result can establish a full-match win.
