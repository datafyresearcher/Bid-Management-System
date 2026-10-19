import logging
import sys
from pathlib import Path

logger = logging.getLogger("bms.bootstrap")


def ensure_seeded():
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        import seed

        seed.main()
    except Exception:
        logger.exception("Startup seed failed")
