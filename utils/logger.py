import logging
import logging.handlers
import os
import sys

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_configured = False


def _setup() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    fh = logging.handlers.TimedRotatingFileHandler(
        os.path.join(LOG_DIR, "scanner.log"),
        when="midnight", backupCount=7, encoding="utf-8",
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    _setup()
    return logging.getLogger(name)


def get_signal_logger() -> logging.Logger:
    _setup()
    sig = logging.getLogger("signals")
    if not sig.handlers:
        sig.propagate = False
        fmt = logging.Formatter(
            "%(asctime)s | SIGNAL | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh = logging.handlers.TimedRotatingFileHandler(
            os.path.join(LOG_DIR, "signals.log"),
            when="midnight", backupCount=30, encoding="utf-8",
        )
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        sig.addHandler(fh)
        sig.setLevel(logging.INFO)
    return sig
