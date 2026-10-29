#!/usr/bin/env python3
"""
SubMgr Main Program Entry
"""

import argparse

from sub_mgr import (
    convert_subscriptions,
    create_subscription,
    install_subscription,
    list_location_links,
    list_subscriptions,
)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="订阅配置转换工具")
    parser.add_argument(
        "-c",
        "--config",
        default="./configs/config.toml",
        help="配置文件路径 (默认: ./configs/config.toml)",
    )

    # 子命令
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # convert 命令
    convert_parser = subparsers.add_parser("convert", help="转换订阅配置")
    convert_parser.add_argument(
        "-o", "--out-dir", default="./out", help="输出目录路径 (默认: ./out)"
    )
    convert_parser.add_argument("--name", required=False, help="订阅项的名称")

    # list 命令
    list_parser = subparsers.add_parser("list", help="列出订阅配置")
    list_subcmds = list_parser.add_subparsers(dest="list_command", help="list 子命令")
    list_subcmds.add_parser("url", help="列出订阅的完整location链接")

    # create 命令
    create_parser = subparsers.add_parser("create", help="创建新的订阅配置")
    create_parser.add_argument("-n", "--name", required=True, help="订阅名称")
    create_parser.add_argument(
        "-s",
        "--sub-url",
        required=True,
        nargs="+",
        dest="sub_urls",
        help="订阅链接 (可指定多个)",
    )

    # install 命令
    install_parser = subparsers.add_parser("install", help="安装订阅配置到服务器")
    install_parser.add_argument(
        "-n", "--name", required=False, help="订阅名称 (默认: 所有启用的订阅)"
    )

    args = parser.parse_args()

    if args.command == "convert":
        convert_subscriptions(args.config, args.out_dir, args.name)
    elif args.command == "list":
        if args.list_command == "url":
            list_location_links(args.config)
        else:
            list_subscriptions(args.config)
    elif args.command == "create":
        create_subscription(args.config, args.name, args.sub_urls)
    elif args.command == "install":
        install_subscription(args.config, args.name)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
