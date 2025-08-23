import os
from pathlib import Path

PROGRAM_VERSION = "1.0.0"
CONFIG_VERSION = 1

BASE_DIR = Path('WebTMData')

if not BASE_DIR.exists():
    BASE_DIR.mkdir(parents=True, exist_ok=True)


STRICT_RULE_CHECK: bool = False

STOKEN_MOSAIC = "*" * 6
BDUSS_MOSAIC = STOKEN_MOSAIC * 3


CONFIRM_EXPIRE = 86400
CONTENT_VALID_EXPIRE = 86400
PID_CACHE_EXPIRE = 86400 * 7


PROGRAM_NAME = "WebTM"
LOG_FILE_NAME = "webtm.log"
LOG_DIR = BASE_DIR / "logs"

USER_DIR = BASE_DIR / 'users'


for i in [
    LOG_DIR,
    USER_DIR
]:
    if not i.exists():
        i.mkdir(parents=True)