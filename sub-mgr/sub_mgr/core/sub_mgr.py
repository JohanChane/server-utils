import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        *,
        emit: Callable[[str], None] = print,
    ) -> bool:
        """
        转换订阅并保存到指定路径
        """
        try:
            emit("开始转换订阅...")
            emit(f"原始订阅URLs: {sub_urls}")

            conversion_url = self.build_conversion_url(
                sub_urls, subscription_opts, append_opts
            )
            emit(f"转换API URL: {conversion_url[:100]}...")  # 只打印前100字符避免太长

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            response = requests.get(conversion_url, headers=headers, timeout=60)
            response.raise_for_status()

            if not response.content:
                emit("错误：API返回空内容")
                return False

            os.makedirs(os.path.dirname(os.path.abspath(dst_path)), exist_ok=True)

            with open(dst_path, "wb") as f:
                f.write(response.content)

            emit(f"✅ 订阅转换成功！配置文件已保存至: {dst_path}")
            emit(f"📁 文件大小: {len(response.content)} 字节")

            return True

        except requests.exceptions.RequestException as e:
            emit(f"❌ 网络请求错误: {e}")
            return False
        except Exception as e:
            emit(f"❌ 转换过程中发生错误: {e}")
            return False

    def _convert_one(self, sub_config: dict, dst_path: str) -> tuple[bool, list[str]]:
        """完成一个订阅的转换和还原，并收集该任务的完整日志。"""
        messages = []
        sub_urls = sub_config["sub_urls"]
        subscription_opts = sub_config.get("opts")
        append_opts = sub_config.get("append_opts")

        if subscription_opts:
            messages.append(f"⚙️  使用自定义选项: {subscription_opts}")
        if append_opts:
            messages.append(f"➕ 追加选项: {append_opts}")

        try:
            success = self.convert_subscription(
                sub_urls,
                dst_path,
                subscription_opts=subscription_opts,
                append_opts=append_opts,
                emit=messages.append,
            )
        except Exception as e:
            messages.append(f"❌ 转换过程中发生错误: {e}")
            success = False

        if success:
            try:
                restore_proxies(dst_path, sub_urls, emit=messages.append)
            except Exception as e:
                messages.append(f"  ⚠️  还原proxies失败: {e}")

        return success, messages

    def batch_convert(
        self, subscriptions: list[dict], out_dir: str, jobs: int = 1
    ) -> dict[str, bool]:
        """
        批量转换多个订阅
        """
        if not isinstance(jobs, int) or jobs < 1:
            raise ValueError("jobs 必须为正整数")

        tasks = []
        destinations = {}

        for i, sub_config in enumerate(subscriptions):
            name = sub_config.get("name", "未命名")
            enable = sub_config.get("enable", True)
            if not enable:
                print(f"\n⏭️  跳过第 {i + 1}/{len(subscriptions)} 个订阅（未启用）")
                print(f"📝 配置名称: {name}")
                continue

            sub_urls = sub_config.get("sub_urls", [])
            dst_path = sub_config.get("dst_path")

            if not sub_urls:
                print(f"❌ 跳过订阅 '{name}'：sub_urls 为空")
                continue
            if not dst_path:
                print(f"❌ 跳过订阅 '{name}'：dst_path 为空")
                continue

            if not os.path.isabs(dst_path):
                dst_path = os.path.join(out_dir, dst_path)

            canonical_path = os.path.normcase(os.path.realpath(dst_path))
            if canonical_path in destinations:
                raise ValueError(
                    f"输出路径冲突: 订阅 '{name}' 与 '{destinations[canonical_path]}' "
                    f"使用相同目标 {dst_path}"
                )
            destinations[canonical_path] = name
            tasks.append((sub_config, dst_path))

        if not tasks:
            return {}

        workers = min(jobs, len(tasks))
        print(f"📋 待转换: {len(tasks)} 个订阅，并发数: {workers}", flush=True)
        results = {}

        def report(sub_config, dst_path, success, messages):
            results[dst_path] = success
            name = sub_config.get("name", "未命名")
            status = "✅ 成功" if success else "❌ 失败"
            print(
                "\n".join(
                    [
                        f"\n[{len(results)}/{len(tasks)}] 订阅 '{name}': {status}",
                        *messages,
                    ]
                ),
                flush=True,
            )

        if jobs == 1:
            for i, (sub_config, dst_path) in enumerate(tasks):
                success, messages = self._convert_one(sub_config, dst_path)
                report(sub_config, dst_path, success, messages)
                if i < len(tasks) - 1:
                    time.sleep(2)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(self._convert_one, sub_config, dst_path): (
                        sub_config,
                        dst_path,
                    )
                    for sub_config, dst_path in tasks
                }
                for future in as_completed(futures):
                    sub_config, dst_path = futures[future]
                    try:
                        success, messages = future.result()
                    except Exception as e:
                        success, messages = False, [f"❌ 订阅处理失败: {e}"]
                    report(sub_config, dst_path, success, messages)

        return {dst_path: results[dst_path] for _, dst_path in tasks}


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
