import logging
import os
from logging.handlers import RotatingFileHandler

from modules.environment import LOG_LEVEL

log_filename = os.path.join(os.getcwd(), "transit-display.log")


log_level = LOG_LEVEL.upper() or logging.INFO

logging.basicConfig(
    level=log_level,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        # writes to log file, rotated since it lives on the Pi's SD card and grew about 440 KB a day unrotated
        RotatingFileHandler(log_filename, maxBytes=1_000_000, backupCount=3),
        logging.StreamHandler(),  # writes to the terminal
    ],
)

logger = logging.getLogger(__name__)
