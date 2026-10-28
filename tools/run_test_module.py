"""Run one test module in a child process and dump every thread, native frames included, if it hangs.

Used by CI for the desktop modules: a hang inside Qt (an audio thread, a blocking stop) shows no
Python frame, so `py-spy dump --native` is run on the child before it is killed. Without py-spy
only the Python frames of the child are printed, through faulthandler.

    python tools/run_test_module.py tests.test_desktop 240
"""

import os
import shutil
import subprocess
import sys

module, seconds = sys.argv[1], int(sys.argv[2])
child = subprocess.Popen([sys.executable, "-c",
                          "import faulthandler, sys, unittest\n"
                          f"faulthandler.dump_traceback_later({seconds + 60}, exit=True)\n"
                          f"sys.exit(not unittest.main(module=None, argv=['unittest', '-v', {module!r}], exit=False).result.wasSuccessful())"],
                         cwd=os.getcwd())
try:
    sys.exit(child.wait(timeout=seconds))
except subprocess.TimeoutExpired:
    print(f"\n{module} is still running after {seconds} s: dumping every thread of pid {child.pid}", flush=True)
    spy = shutil.which("py-spy")
    if spy:
        subprocess.run([spy, "dump", "--pid", str(child.pid), "--native"], timeout=120)
    else:
        print("py-spy is not installed: install it to see the native frames", flush=True)
    child.kill()
    child.wait()
    sys.exit(1)
