"""Run every tests/test_*.py in its own process.  Exit code 0 only if all pass.  Needs a display on Linux (xvfb-run)."""
import glob
import os
import re
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
failed = []
for f in sorted(glob.glob(os.path.join(here, "test_*.py"))):
    r = subprocess.run([sys.executable, f], capture_output=True, text=True, timeout=300)
    last = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
    m = re.search(r"(\d+) passed, (\d+) failed", last)
    good = r.returncode == 0 and (m is None or m.group(2) == "0") and "\nFAIL" not in "\n" + r.stdout
    print(("ok   " if good else "FAIL ") + os.path.basename(f) + "  " + last)
    if not good:
        failed.append(f)
        print((r.stdout + r.stderr)[-1500:])
print("ALL PASSED" if not failed else f"{len(failed)} FAILED")
sys.exit(1 if failed else 0)
