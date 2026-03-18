"""Logging setup for the signal engine."""
import logging
import sys
from src.config.settings import Settings


def setup_logger(settings: Settings) -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level, logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not root.handlers:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)

        if settings.log_file:
            fh = logging.FileHandler(settings.log_file, encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)

    return root
