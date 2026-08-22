from __future__ import annotations

import os
import time
from pathlib import Path

pid_file = Path(os.environ["PMGS_TEST_PID_FILE"])
pid_file.write_text(str(os.getpid()), encoding="utf-8")

while True:
    time.sleep(60)
