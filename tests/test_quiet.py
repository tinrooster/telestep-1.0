import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import subprocess, telestep_core
# On Windows every child process must be started without a console window; elsewhere nothing changes.
if sys.platform == "win32":
    p = subprocess.Popen(["cmd", "/c", "exit 0"]); p.wait()
    assert getattr(subprocess.Popen, "_telestep_quiet", False), "Popen not patched"
else:
    assert not getattr(subprocess.Popen, "_telestep_quiet", False)
    r = subprocess.run(["true"]); assert r.returncode == 0
print("1 passed, 0 failed")
