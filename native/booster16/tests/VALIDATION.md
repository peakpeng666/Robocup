# Foundation validation, 2026-10-24 UTC

Scope: only `core/controller.cpp` and `tests/core_test.cpp`. Not a simulation,
official policy, vendor ABI, robot safety or match-performance validation.

- g++ C++17, `-Wall -Wextra -Wpedantic -Werror -O0 -g`: PASS, 96 checks.
- g++ C++17, `-Wall -Wextra -Wpedantic -Werror -O2 -DNDEBUG`: PASS, 96 checks.
- AddressSanitizer + UndefinedBehaviorSanitizer, `-O1 -g`, leak detection
  disabled (`ASAN_OPTIONS=detect_leaks=0`): PASS, 96 checks.
- LeakSanitizer: BLOCKED by the execution environment (fatal diagnostic:
  LeakSanitizer does not work under ptrace). No leak-clean claim is made.

The fixtures validate explicit unavailable-backend errors as well as integer
clock/reset, golden replay, independent robot instances, invalid numerical
values, mismatched outputs, mode semantics, and hybrid-effort saturation.
The counter fixture is test-only and is not a walking fallback.

Reproduce the first two configurations with `bash run_core_tests.sh` from this
directory. Binaries are created in an isolated temporary directory and removed.
