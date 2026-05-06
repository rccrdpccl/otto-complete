import logging
import sys


def setup_logging(level: str = "INFO"):
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)-5s %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z")
    )
    root.addHandler(handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
