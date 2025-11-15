import argparse
import os
from pathlib import Path


def parse_cli_overrides():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--webui-dir", dest="webui_dir")
    parser.add_argument("--webui-zip", dest="webui_zip")
    parser.add_argument("--webui-server", dest="webui_server")
    args, _ = parser.parse_known_args()

    if args.webui_dir:
        webui_dir = Path(args.webui_dir).expanduser().resolve()
        os.environ["WTM_WEBUI_DIR"] = str(webui_dir)

    if args.webui_zip:
        webui_zip = Path(args.webui_zip).expanduser().resolve()
        os.environ["WTM_WEBUI_ZIP"] = str(webui_zip)

    if args.webui_server:
        os.environ["WTM_WEBUI_SERVER"] = args.webui_server


def main():
    parse_cli_overrides()

    from src.api import Server
    from src.core.initialize import initialize

    initialize()
    Server.run()


if __name__ == "__main__":
    main()
