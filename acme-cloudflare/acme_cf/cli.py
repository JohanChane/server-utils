import argparse
import sys
from pathlib import Path

from acme_cf.commands import cmd_apply, cmd_check, cmd_install, cmd_list, cmd_refresh
from acme_cf.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="acme-cf", description="ACME SSL cert management with Cloudflare DNS"
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config.jsonc",
        help="path to config.jsonc (default: config.jsonc)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_apply = sub.add_parser("apply", help="issue SSL certs via acme.sh")
    p_apply.add_argument(
        "--force", action="store_true", help="force renew even if not expired"
    )

    sub.add_parser("install", help="install certs to nginx ssl path")
    sub.add_parser("check", help="check cert expiration via openssl")
    sub.add_parser("refresh", help="purge Cloudflare cache")
    sub.add_parser("list", help="list certs from acme.sh")

    args = parser.parse_args()

    config_path = Path(args.config)
    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.command == "apply":
        cmd_apply(config, force=args.force)
    elif args.command == "install":
        cmd_install(config)
    elif args.command == "check":
        cmd_check(config)
    elif args.command == "refresh":
        cmd_refresh(config)
    elif args.command == "list":
        cmd_list(config)
