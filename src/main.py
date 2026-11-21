import argparse
import asyncio
import contextlib
import faulthandler
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from config import DESCRIPTION, DISPLAY_NAME, VERSION, Config, log_path
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
    log_crashes()


def log_crashes():
    """Log uncaught exceptions from any thread, and tracebacks of hard crashes (e.g. in rtmidi's C++ code)"""
    log = logging.getLogger("crash")
    sys.excepthook = lambda kind, error, trace: log.critical("Uncaught exception", exc_info=(kind, error, trace))
    threading.excepthook = lambda hook: log.critical(
        "Uncaught exception in thread %s", hook.thread and hook.thread.name, exc_info=(hook.exc_type, hook.exc_value, hook.exc_traceback)
    )
    global _crash_file  # kept open, faulthandler writes to it while the process dies
    _crash_file = open(log_path().with_name("crash.log"), "a", encoding="utf-8")
    faulthandler.enable(_crash_file, all_threads=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--no-tray", action="store_true", help="run in the console without the tray icon")
    parser.add_argument("--button-test", action="store_true", help="log Platform M+ buttons, faders and encoders, lighting buttons while held")
    args = parser.parse_args()

    setup_logging()
    logging.getLogger(__name__).info("%s %s starting", DISPLAY_NAME, VERSION)
    if args.button_test:
        import button_test

        return button_test.run()

    config = Config.load()
    sync = Dot2PMPSync(config.dot2_host, config.dot2_password)

    if args.no_tray:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(sync.run())
        return 0

    import tray  # only the tray needs Qt

    return tray.run(sync, config)


if __name__ == "__main__":
    sys.exit(main())
