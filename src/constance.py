import sys
from pathlib import Path

MAIN_SERVER = "https://webtm.tbw.icu"

DEV = "dev" in sys.argv or "--dev" in sys.argv
DEBUG = "--debug" in sys.argv

PROGRAM_VERSION = "1.0.0"
CONFIG_VERSION = 1
WEB_UI_VERSION = "croissant"


COOKIE_MIN_MOSAIC_LENGTH = 6


CONFIRM_EXPIRE = 86400
CONTENT_VALID_EXPIRE = 86400
PID_CACHE_EXPIRE = 86400 * 7
CODE_EXPIRE = 86400

BASE_DIR = Path("WebTMData")

PROGRAM_NAME = "WebTM"
USER_DIR = BASE_DIR / "users"
LOG_FILE_NAME = "webtm.log"
LOG_DIR = BASE_DIR / "logs"
SYSTEM_CONFIG_PATH = BASE_DIR / "config.toml"


DEFAULT_SERVER_PORT = 36799


for i in [LOG_DIR, USER_DIR]:
    if not i.exists():
        i.mkdir(parents=True)
