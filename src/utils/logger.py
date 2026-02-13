import logging
import sys
from pathlib import Path


def setup_logger(name: str, level: str = "INFO", log_file: str = None):
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[],
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    root_logger.handlers = []

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    http_level = logging.DEBUG if level.upper() == "DEBUG" else logging.WARNING
    logging.getLogger("httpx").setLevel(http_level)
    logging.getLogger("httpcore").setLevel(http_level)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    logger = logging.getLogger(name)
    return logger


def get_logger(name: str):
    return logging.getLogger(name)
