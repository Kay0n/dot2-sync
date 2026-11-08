import argparse
import asyncio
import contextlib
import logging
import sys
from logging.handlers import RotatingFileHandler

import autostart
from config import VERSION, Config, log_path
from sync import Dot2PMPSync


def setup_logging():
    log_path().parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_path(), maxBytes=1_000_000, backupCount=1, encoding="utf-8"),
    ]
    if sys.stderr is not None:  # None without a console (pythonw, --windowed build)
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync a dot2 console with an Icon Platform M+")
    parser.add_argument("--no-tray", action="store_true", help="run in the console without the tray icon")
    args = parser.parse_args()

    setup_logging()
    logging.getLogger(__name__).info("dot2 Sync %s starting", VERSION)
    config = Config.load()
    sync = Dot2PMPSync(config.dot2_host, config.dot2_password)

    if args.no_tray:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(sync.run())
        return 0

    autostart.update()
    import tray  # only the tray needs Qt

    return tray.run(sync, config)


if __name__ == "__main__":
    sys.exit(main())
