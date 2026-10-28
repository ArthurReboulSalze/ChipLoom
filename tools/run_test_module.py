"""Run one test module and print every thread's stack if it hangs.

Used by CI for the desktop modules: a native Qt or audio hang otherwise ends in a silent kill.

    python tools/run_test_module.py tests.test_desktop 240
"""

import faulthandler
import os
import sys
import unittest

module, seconds = sys.argv[1], int(sys.argv[2])
sys.path.insert(0, os.getcwd())
faulthandler.dump_traceback_later(seconds, exit=True)
result = unittest.main(module=None, argv=[sys.argv[0], "-v", module], exit=False).result
sys.exit(0 if result.wasSuccessful() else 1)
