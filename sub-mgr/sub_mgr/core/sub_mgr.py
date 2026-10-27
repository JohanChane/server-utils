import os
import time
from urllib.parse import quote

import requests
import tomli
import tomli_w

from .proxy_restorer import restore_proxies


class SubscriptionConverter:
    def __init__(self, base_url=None, config_url=None, opts=None):
        self.base_url = base_url
        self.config_url = config_url
        self.opts = opts or {}

    def encode_subscription_urls(self, sub_urls: list[str]) -> str:
        """对订阅URL进行编码处理"""
        # 将多个订阅URL用|连接
        combined_urls = "|".join(sub_urls)
        # URL编码
        encoded_urls = quote(combined_urls, safe="")
        return encoded_urls

    def build_conversion_url(
        self, sub_urls: list[str], subscription_opts=None, append_opts=None
    ) -> str:
        """构建转换URL"""
        encoded_urls = self.encode_subscription_urls(sub_urls)

        # 合并选项：全局opts + 订阅级append_opts + 订阅级opts（覆盖）
        final_opts = self.opts.copy()

        # 先追加append_opts
        if append_opts:
            final_opts.update(append_opts)

        # 最后用subscription_opts覆盖（优先级最高）
        if subscription_opts:
            final_opts.update(subscription_opts)

        # 构建基础URL
        conversion_url = (
            f"{self.base_url}?url={encoded_urls}&config={quote(self.config_url)}"
        )

        # 添加配置选项
        for key, value in final_opts.items():
            conversion_url += f"&{key}={str(value).lower()}"

        # 添加固定参数
        fixed_params = {
            "insert": "false",
            "emoji": "true",
            "tfo": "false",
            "scv": "true",
            "fdn": "false",
            "expand": "true",
            "sort": "false",
            "new_name": "true",
        }

        for key, value in fixed_params.items():
            conversion_url += f"&{key}={value}"

        return conversion_url

    def convert_subscription(
        self,
        sub_urls: list[str],
        dst_path: str,
        subscription_opts=None,
        append_opts=None,
    ) -> bool:
        """
        转换订阅并保存到指定路径
        """
        try:
            print("开始转换订阅...")
            print(f"原始订阅URLs: {sub_urls}")

            conversion_url = self.build_conversion_url(
                sub_urls, subscription_opts, append_opts
            )
            print(f"转换API URL: {conversion_url[:100]}...")  # 只打印前100字符避免太长

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            response = requests.get(conversion_url, headers=headers, timeout=60)
            response.raise_for_status()

            if not response.content:
                print("错误：API返回空内容")
                return False

            os.makedirs(os.path.dirname(os.path.abspath(dst_path)), exist_ok=True)

            with open(dst_path, "wb") as f:
                f.write(response.content)

            print(f"✅ 订阅转换成功！配置文件已保存至: {dst_path}")
            print(f"📁 文件大小: {len(response.content)} 字节")

            return True

        except requests.exceptions.RequestException as e:
            print(f"❌ 网络请求错误: {e}")
            return False
        except Exception as e:
            print(f"❌ 转换过程中发生错误: {e}")
            return False

    def batch_convert(self, subscriptions: list[dict], out_dir: str) -> dict[str, bool]:
        """
        批量转换多个订阅
        """
        results = {}

        for i, sub_config in enumerate(subscriptions):
            enable = sub_config.get("enable", True)
            if not enable:
                print(f"\n⏭️  跳过第 {i + 1}/{len(subscriptions)} 个订阅（未启用）")
                print(f"📝 配置名称: {sub_config.get('name', '未命名')}")
                continue

            print(f"\n🔧 正在处理第 {i + 1}/{len(subscriptions)} 个订阅...")
            print(f"📝 配置名称: {sub_config.get('name', '未命名')}")

            sub_urls = sub_config.get("sub_urls", [])
            dst_path = sub_config.get("dst_path")
            subscription_opts = sub_config.get("opts")
            append_opts = sub_config.get("append_opts")

            if not sub_urls:
                print("❌ 跳过：sub_urls 为空")
                continue
            if not dst_path:
                print("❌ 跳过：dst_path 为空")
                continue

            if subscription_opts:
                print(f"⚙️  使用自定义选项: {subscription_opts}")
            if append_opts:
                print(f"➕ 追加选项: {append_opts}")

            if not os.path.isabs(dst_path):
                dst_path = os.path.join(out_dir, dst_path)

            success = self.convert_subscription(
                sub_urls,
                dst_path,
                subscription_opts=subscription_opts,
                append_opts=append_opts,
            )
            results[dst_path] = success

            if success:
                restore_proxies(dst_path, sub_urls)

            if i < len(subscriptions) - 1:
                time.sleep(2)

        return results


def load_config_from_toml(config_path: str) -> dict:
    """从TOML配置文件加载完整配置"""
    try:
        with open(config_path, "rb") as f:
            config = tomli.load(f)
        return config
    except FileNotFoundError:
        print(f"❌ 配置文件 {config_path} 不存在")
        return {}
    except Exception as e:
        print(f"❌ 加载配置文件失败: {e}")
        return {}


def save_config_to_toml(config_data: dict, config_path: str):
    """保存配置到TOML文件"""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(config_path)), exist_ok=True)
        with open(config_path, "wb") as f:
            tomli_w.dump(config_data, f)
        print(f"✅ 配置已保存到: {config_path}")
    except Exception as e:
        print(f"❌ 保存配置失败: {e}")
