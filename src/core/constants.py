import os
import sys
from pathlib import Path

PROGRAM_VERSION = "1.1.1"
IS_EXE = hasattr(sys, "frozen")

DEV = "dev" in sys.argv or "--dev" in sys.argv
DEBUG = "--debug" in sys.argv
PUBLIC = "--public" in sys.argv
DEV_WEBUI = "--dev-webui" in sys.argv

MAIN_SERVER = os.getenv("WTM_MAIN_SERVER", "https://webtm.tbw.icu")
DEFAULT_SERVER_PORT = 36799
TRUSTED_PROXIES = os.getenv("WTM_TRUSTED_PROXIES", "127.0.0.1").split(",")

if DEV or DEV_WEBUI:
    ALLOW_ORIGINS = ["*"]
elif allow_origins_env := os.getenv("WTM_ALLOW_ORIGINS"):
    ALLOW_ORIGINS = [i.strip() for i in allow_origins_env.split(",") if i.strip()]
else:
    ALLOW_ORIGINS = [MAIN_SERVER]

WEB_UI_CODE = os.getenv("WTM_WEB_UI_CODE", "Ceylon")

COOKIE_MIN_MOSAIC_LENGTH = 6

CONFIRM_EXPIRE = 86400
CONTENT_VALID_EXPIRE = 86400
PID_CACHE_EXPIRE = 86400 * 7
INVITE_CODE_EXPIRE = 86400 * 7


PROJECT_ROOT = Path(sys.executable).parent.resolve() if IS_EXE else Path(__file__).resolve().parents[2]
BASE_DIR = Path(os.getenv("WTM_BASE_DIR", PROJECT_ROOT / "WebTMData")).resolve()
RESOURCE_DIR = Path(os.getenv("WTM_RESOURCES_DIR", PROJECT_ROOT / "resources")).resolve()

USER_DIR = BASE_DIR / "users"
LOG_FILE_NAME = "webtm.log"
LOG_DIR = BASE_DIR / "logs"
SYSTEM_CONFIG_PATH = BASE_DIR / "config.toml"


for i in [LOG_DIR, USER_DIR]:
    if not i.exists():
        i.mkdir(parents=True)
