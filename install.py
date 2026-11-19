"""仓库根目录便捷安装入口：转发至 wf-mode/host/install.py。"""

from __future__ import annotations

import sys
from pathlib import Path

WF_MODE = Path(__file__).resolve().parent / "wf-mode"
if str(WF_MODE) not in sys.path:
    sys.path.insert(0, str(WF_MODE))

from host.install import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
