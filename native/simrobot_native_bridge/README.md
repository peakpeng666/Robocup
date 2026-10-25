# SimRobot native 1.7 bridge (Booster K1)

Branch: `local/simrobot-native-bridge`. Under the owner's 2026-10-26 cleanup and
backup instruction, source is synchronized to `codex/native17-foundation-20261026`
on GitHub. The experiment remains separate from the mainline.

Completed-run bulk data is preserved in the encrypted
[`foundation-data-20261026_012348` release](https://github.com/peakpeng666/Robocup/releases/tag/foundation-data-20261026_012348).
`REMOTE-DATA-20261026.json` files identify the removed data and restore index in
the main local workspace. Source, the baseline executable variant, configurations,
models and installed environments remain local.

## Goal

Bring the cloud-rebuilt **Booster K1 native motion control (official simulated
firmware 1.7.1.0-release-00154-2026-07-14)** into the local B-Human / SimRobot
stack:

```
SimRobot sensors → B-Human vision & state estimation → behavior → MotionRequest
→ native 1.7 core (nested policy, serial motor output, kick/pass, lifecycle,
supine get-up) → hybrid actuator leases → physics
```

The official B-Human gait and normal camera perception stay untouched; the
native core only replaces the Motion thread outputs on explicitly selected
robots/scenarios. The ARM/QEMU forge 1.6.0.10 route stays a separate mode —
models, configs and programs of the two routes never mix (field names are
suffixed `native17*` vs forge's ARM fields).

## Status (2026-10-24)

Done on this machine:

- Verified interface facts against the local sources (see `INTERFACES.md`).
- Imported the reusable, publicly verified booster16 patches into `patches/`
  with a source manifest (`patches/SOURCE_MANIFEST.json`), origin
  `origin/adapt/booster16-simrobot @ 1f2e161c`.
- Patch applicability re-verified on fresh copies with
  `GIT_CEILING_DIRECTORIES` (evidence
  `evidence/20261024_223108-patch-verification/`):
  - delay-ring → hybrid-actuator: apply cleanly to bhuman-local `Util/SimRobot`.
  - referee-frame-export: applies cleanly to the clean 2e3374 baseline
    (BHumanCodeRelease), but **not** to bhuman-local (its local audit-hook
    insert in `RoboCupCtrl.cpp::update` breaks the context). Not needed for
    the minimal native 1.7 layer; if ever needed in a bhuman-local variant it
    must be re-based as a clearly-labeled bridge-side adaptation.
- `tools/verify_package.py` written and self-tested (9/9 cases: split-volume
  merge, size/SHA-256 checks, read-only archiving, hostile tar rejection —
  absolute paths, `..`, escaping symlinks, device nodes — and manifest hash
  mismatch). Self-test evidence under `evidence/*-verify-package-selftest/`.
- `tools/make_variant.py` + `tools/build_variant.sh` written (forge-style
  variant discipline, standalone). A baseline variant
  (bhuman-local + the two SimRobot patches only) exists under `work/` to prove
  the patches also compile.
- `launch/run_native_bridge.py` single entry with explicit `--backend`.

Blocked on the owner:

- **The evidence package `native_harness_sources_evidence_20261024.tar.gz`
  (63,478,869 bytes, SHA-256
  `94e2ddeec14525f303958aa61e89eb57102a9814eb9b1f68534b6b4146b09ae5`) has not
  arrived yet** — not on this machine (~/Downloads, ~/Desktop, /tmp), not in
  any GitHub release (incl. drafts) of peakpeng666/robocup as of 2026-10-24
  ~22:25 JST. The owner was splitting it into volumes for upload. **Tell me
  the volume location (release tag, local path, or link) to unblock.**

## Layout

```
native/simrobot_native_bridge/
  README.md, INTERFACES.md
  patches/        imported SimRobot patches + SOURCE_MANIFEST.json; later also
                  the B-Human-side bridge patches (native17 integration)
  tools/          verify_package.py (+ self-test), make_variant.py,
                  build_variant.sh
  src/            session adapter code (written after the package is verified)
  vendor/native_core_17/   package core files, byte-identical, with
                  SOURCE_MANIFEST.json (created after verification)
  launch/run_native_bridge.py    the only launch entry
  evidence/<timestamp>-*/       small text evidence (tracked)
  work/           packages, unpacked trees, variants, builds, videos
                  (gitignored scratch; never written into bhuman-local or
                  forge/variants)
```

## Workflow

1. **Package arrival** — `tools/verify_package.py <volumes-or-dir>` merges the
   volumes, checks size + SHA-256, archives the original read-only, unpacks
   defensively, verifies `artifact_manifest.json` per-file hashes, and writes
   `evidence/<ts>-package-verification/package-verification.json`. Nothing in
   the package is executed.
2. **Study & vendor** — read the core (lifecycle, nested policy math, serial
   motor output, kick, get-up, skill contracts, fk) per `INTERFACES.md`'s
   open-question list; vendor byte-identical files under
   `vendor/native_core_17/` with a SOURCE_MANIFEST.
3. **Variant** — `tools/make_variant.py --name variant-<ts>_native17
   --patch <bhuman-side patches>` (the two SimRobot patches are always applied
   first), then `tools/build_variant.sh variant-<ts>_native17 [jobs]`.
   Products stay inside the variant.
4. **Run** — `launch/run_native_bridge.py --backend native17 --scene <scene>`
   (prerequisites are checked and reported). Other backends:
   `--backend bhuman -- gait|match ...` (official entry, untouched),
   `--backend arm16 -- <forge CLI args>` (forge route, invoked as-is).

## Hard constraints honored here

- Local simulation/training only; no robot connection, no firmware `.run`
  installers, no flashing, no system service/network changes.
- `bhuman/local-k1-validation-20261019/bhuman-local` and
  `bhuman/BHumanCodeRelease` are never written by this workspace (variants are
  separate copies; the official entry and its 19 hash-protected files stay
  intact).
- Official B-Human gait + normal camera perception stay default; the native
  1.7 core is opt-in via explicit scenario/robot selection.
- Native core math files stay byte-identical (modifications need a dedicated
  commit with rationale, failing sample, and regression results).
- One torque computation per joint and step: the adapter never adds a second
  PD; hybrid actuator leases are refreshed every 2 ms physics step and any
  rejection disables all joints and stops the simulation (no silent fallback
  to the legacy PD).
- Evidence: original data read-only; every validation run gets a fresh
  timestamped directory; failures are kept.
- Source backups use the named experiment branch. No credentials, recovery keys,
  vendor firmware or private weights are committed.

## Base lines

- B-Human `2e3374ba896da8288607f9a1881b876642fe18b8` (+ local audit hooks in
  the runnable copy `bhuman/local-k1-validation-20261019/bhuman-local`).
- SimRobot `9deb6ae6b2a553211612affb757490736f96bfb3` (ServoMotor matches
  this baseline in bhuman-local).
