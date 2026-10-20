"""Use the driver-compatible pip Warp before Kit loads its bundled Warp 1.7.1.

Warp 1.8.1 fixes NVIDIA/warp#851 for R580+ drivers. This entry point keeps the
Isaac Sim installation intact while letting scripts use the corrected package.
"""
import runpy
import sys
from pathlib import Path

import warp  # noqa: F401 -- must precede AppLauncher / SimulationApp

if len(sys.argv) < 2:
    raise SystemExit('Usage: run_script.py SCRIPT [ARGS...]')
script = Path(sys.argv[1]).resolve()
sys.argv = [str(script), *sys.argv[2:]]
sys.path.insert(0, str(script.parent))
runpy.run_path(str(script), run_name='__main__')
