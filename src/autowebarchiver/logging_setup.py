from __future__ import annotations

import logging
import os
import sys


def setup_logging() -> None:
    level = logging.DEBUG if os.environ.get("AUTOWEBARCHIVER_DEBUG") else logging.INFO
    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
