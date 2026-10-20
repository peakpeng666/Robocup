import sys

# Preview 4's native import segfaults for a multiline JSON argv value on
# this runtime. Fail before entering native code; wrappers serialize compact JSON.
if any('\n' in arg or '\r' in arg for arg in sys.argv[1:]):
    raise SystemExit('Multiline command arguments are unsafe for this Isaac Gym binding; pass compact --config_patch JSON.')

import isaacgym
from utils.runner import Runner
from utils.runner_history_symmetry import Runner_History
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--history",
        action="store_true",
        help="Use the history runner"
    )

    args, _ = parser.parse_known_args()

    if args.history:
        sys.argv.remove("--history")
        runner = Runner_History(test=False)
    else:
        runner = Runner(test=False)

    try:
        runner.train()
    finally:
        if hasattr(runner, "recorder"):
            runner.recorder.writer.flush()
            runner.recorder.writer.close()
        runner.env.close()

