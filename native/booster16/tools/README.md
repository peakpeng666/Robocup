# Booster 1.6 package inventory (read-only)

Run against **one selected, already unpacked package directory**, not a home
folder, robot, complete filesystem, or unrelated project collection:

```sh
python3 native/booster16/tools/inspect_package.py /selected/package > inventory.json
python3 -m unittest discover -s native/booster16/tools -p 'test_*.py' -v
```

No third-party Python dependencies. Linux/Python 3 required; host
`/usr/bin/readelf` or `/bin/readelf` is optional. `--no-readelf` skips it.
The inspector never executes an input artifact, never calls `ldd`, never
extracts an archive/installer, and never writes to the selected package.
Shell redirection writes only the user-selected report.

Defaults: 10,000 entries, 12 directory levels, 512 MiB per file, 2 GiB total
hashed bytes. CLI flags `--max-entries`, `--max-depth`, `--max-file-bytes`,
`--max-total-bytes` change these bounds. Limits produce `complete: false`.
Archives/installers are inventoried as unopened opaque files, not proof of
their contents. Large vendor bundles may exceed the default per-file limit.

Only selected names/extensions are read: mck, Webots interface/shared
libraries, SDK, policy models, configuration, version/manifest/release
metadata, and archives/installers. Dotfiles/directories, common key and
credential names, and symlinks are excluded. Directories are opened with
no-follow descriptors; FIFO/device files are not read. Exclusions contain
reason counts, not credential contents or sensitive filenames. This is a
conservative filename filter, **not a secret scanner**: inspect a dedicated
vendor package, never a mixed personal directory. File hashes and filenames
may themselves be private; do not publish reports automatically.

ELF architecture is header evidence only, not proof that a binary loads or
implements the required controller. NEEDED names come from a bounded-time
host readelf invocation on the open file descriptor, with a 1 MiB combined
stdout/stderr streaming cap and 5-second timeout. Overflow or timeout kills
and reaps the parser and returns no partial NEEDED list; no input executable is
launched. The optional parser is not a hardened malicious-binary sandbox;
use `--no-readelf` for untrusted inputs. Version claims are numeric matches
from the first 64 KiB of explicit metadata files, with line numbers, not
verified release identities. File names are never promoted to version proof.

`native_1_6_availability` intentionally remains `unknown`, even when an x86
mck-shaped file exists. A same-version manifest/build identity, original
policy/configuration, and interface/time/reset contracts still require
independent verification. An x86 SDK archive is explicitly **not** an x86
motion core. This tool cannot establish simulation compatibility or gait
parity, and has not inspected a real 1.6 vendor bundle during its tests.

Output contract: `inventory.schema.json` (JSON Schema 2020-12).
