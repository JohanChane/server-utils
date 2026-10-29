import os
import unicodedata
import uuid

from .core.sub_mgr import (
    SubscriptionConverter,
    load_config_from_toml,
    save_config_to_toml,
)


def _disp_width(s: str) -> int:
    """计算字符串的显示宽度，CJK 和全角字符宽度计为 2"""
    w = 0
    for ch in s:
        eaw = unicodedata.east_asian_width(ch)
        w += 2 if eaw in ("F", "W") else 1
    return w


def _trunc(s: str, width: int) -> str:
    """按显示宽度截断字符串，超出部分用 ... 代替"""
    dw = 0
    for i, ch in enumerate(s):
        eaw = unicodedata.east_asian_width(ch)
        chw = 2 if eaw in ("F", "W") else 1
        if dw + chw > width - 2:
            return s[:i] + "…"
        dw += chw
    return s


def _pad(s: str, width: int) -> str:
    """按显示宽度填充字符串"""
    dw = _disp_width(s)
    return s + " " * max(0, width - dw)


def list_subscriptions(config_path: str):
    """列出所有订阅配置"""
    config = load_config_from_toml(config_path)
    if not config:
        print("❌ 配置文件加载失败")
        return

    subscriptions = config.get("subscriptions", [])
    if not subscriptions:
        print("❌ 没有找到订阅配置")
        return

    print(f"📋 找到 {len(subscriptions)} 个订阅配置")
    print("\n" + "=" * 60)
    header = (
        f"{_pad('名称', 18)} {_pad('目标路径', 24)} {_pad('订阅URL数量', 12)} {'状态'}"
    )
    print(header)
    print("-" * 60)

    for sub in subscriptions:
        name = sub.get("name", "未命名")
        dst_path = sub.get("dst_path", "未设置")
        sub_urls = sub.get("sub_urls", [])
        enable = sub.get("enable", True)
        status = "✅ 启用" if enable else "❌ 禁用"

        print(
            f"{_pad(name, 18)} {_pad(_trunc(dst_path, 24), 24)} {_pad(str(len(sub_urls)), 12)} {status}"
        )

    print("=" * 60)


def list_location_links(config_path: str):
    """列出订阅的完整location链接"""
    config = load_config_from_toml(config_path)
    if not config:
        print("❌ 配置文件加载失败")
        return

    # 获取location配置
    settings_config = config.get("settings", {})
    location_base = settings_config.get("location")

    if not location_base:
        print("❌ 配置文件中未找到 location 配置")
        print('请在 [settings] 部分添加 location = "https://example.com/file/"')
        return

    subscriptions = config.get("subscriptions", [])
    if not subscriptions:
        print("❌ 没有找到订阅配置")
        return

    print("📍 基于 location 生成订阅链接")
    print(f"📁 基础路径: {location_base}")
    print("\n" + "=" * 80)

    enabled_count = 0
    for sub in subscriptions:
        # 只处理启用的订阅
        enable = sub.get("enable", True)
        if not enable:
            continue

        name = sub.get("name", "未命名")
        dst_path = sub.get("dst_path", "")

        if dst_path:
            # 拼接完整的location链接
            full_link = location_base.rstrip("/") + "/" + dst_path.lstrip("/")
            print(f"{name}: {full_link}")
            enabled_count += 1

    print("=" * 80)
    print(f"📊 总计: {enabled_count} 个启用的订阅配置")


def convert_subscriptions(config_path: str, out_dir: str, name: str):
    """转换订阅配置"""
    config = load_config_from_toml(config_path)
    if not config:
        print("❌ 配置文件加载失败")
        return

    subscriptions = config.get("subscriptions", [])
    if not subscriptions:
        print("❌ 没有找到有效的订阅配置")
        return

    for sub in subscriptions:
        if name and sub.get("name") == name:
            subscriptions = [sub]
            break
    print(f"📋 找到 {len(subscriptions)} 个订阅配置")

    # 从配置中获取转换器参数
    converter_config = config.get("converter", {})
    base_url = converter_config.get("base_url")
    config_url = converter_config.get("config_url")
    opts = converter_config.get("opts", {})

    # 创建转换器实例
    converter = SubscriptionConverter(
        base_url=base_url, config_url=config_url, opts=opts
    )

    # 打印使用的配置
    print(f"🔧 使用转换服务: {converter.base_url}")
    print(f"📄 使用规则配置: {converter.config_url}")
    print(f"⚙️  全局转换选项: {converter.opts}")

    # 检查并创建输出目录
    if not os.path.exists(out_dir):
        print(f"📁 创建输出目录: {out_dir}")
        os.makedirs(out_dir, exist_ok=True)
    else:
        print(f"📁 使用现有输出目录: {out_dir}")

    results = converter.batch_convert(subscriptions, out_dir)

    # 打印结果摘要
    print("\n" + "=" * 50)
    print("📊 转换结果摘要:")
    success_count = 0
    for path, success in results.items():
        status = "✅ 成功" if success else "❌ 失败"
        print(f"  {path}: {status}")
        if success:
            success_count += 1

    print(f"\n🎯 总计: {success_count}/{len(subscriptions)} 个订阅转换成功")


def quick_convert(sub_urls: list[str], dst_path: str):
    """快速转换单个订阅"""
    converter = SubscriptionConverter()
    converter.convert_subscription(sub_urls, dst_path)


def install_subscription(config_path: str, name: str | None = None):
    """安装订阅配置到服务器"""
    config = load_config_from_toml(config_path)
    if not config:
        print("❌ 配置文件加载失败")
        return

    subscriptions = config.get("subscriptions", [])
    if not subscriptions:
        print("❌ 没有找到订阅配置")
        return

    if name:
        subs_to_install = [sub for sub in subscriptions if sub.get("name") == name]
        if not subs_to_install:
            print(f"❌ 没有找到名称为 '{name}' 的订阅配置")
            return
    else:
        subs_to_install = [sub for sub in subscriptions if sub.get("enable", True)]

    if not subs_to_install:
        print("❌ 没有找到可安装的订阅配置")
        return

    settings_config = config.get("settings", {})
    install_dir = settings_config.get("install_dir")

    if not install_dir:
        print("❌ 配置文件中未找到 install_dir 配置")
        print('请在 [settings] 部分添加 install_dir = "/path/to/install/dir"')
        return

    import subprocess

    for sub in subs_to_install:
        sub_name = sub.get("name", "未命名")
        dst_dir = os.path.join(install_dir, os.path.dirname(sub.get("dst_path", "")))
        src_dir = os.path.join(
            config.get("base_dir", "./out"), os.path.dirname(sub.get("dst_path", ""))
        )

        print(f"📦 正在安装订阅 '{sub_name}' 到服务器...")
        print(f"📁 安装路径: {dst_dir}")

        try:
            subprocess.run(
                ["sudo", "mkdir", "-p", os.path.dirname(dst_dir)], check=True
            )
            subprocess.run(
                ["sudo", "rsync", "-a", src_dir + "/", dst_dir + "/"], check=True
            )
            print(f"✅ 订阅 '{sub_name}' 安装完成")
        except subprocess.CalledProcessError as e:
            print(f"❌ 以管理员权限复制目录失败: {e}")


def create_subscription(config_path: str, name: str, sub_urls: list[str]):
    """创建新的订阅配置"""
    config = load_config_from_toml(config_path)
    if not config:
        print("❌ 配置文件加载失败")
        return

    if not sub_urls:
        print("❌ 至少需要指定一个 sub-url")
        return

    subscriptions = config.get("subscriptions", [])

    for sub in subscriptions:
        if sub.get("name") == name:
            print(f"❌ 订阅名称 '{name}' 已存在")
            return

    dst_path = f"{uuid.uuid4()}/clash.yaml"

    new_sub = {
        "name": name,
        "enable": True,
        "sub_urls": sub_urls,
        "dst_path": dst_path,
    }

    subscriptions.append(new_sub)
    config["subscriptions"] = subscriptions

    save_config_to_toml(config, config_path)
    print(f"✅ 创建订阅 '{name}' 成功")
    print(f"📁 目标路径: {dst_path}")
