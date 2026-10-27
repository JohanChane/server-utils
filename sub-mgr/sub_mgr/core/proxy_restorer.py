import requests
import yaml


def _fetch_proxies_from_url(url: str) -> list:
    resp = requests.get(url, headers={"User-Agent": "mihomo"}, timeout=30)
    resp.raise_for_status()
    data = yaml.safe_load(resp.text)
    if isinstance(data, dict) and "proxies" in data:
        return data["proxies"]
    return []


def _collect_original_proxies(sub_urls: list) -> dict:
    original_map = {}
    for url in sub_urls:
        if not url.startswith(("http://", "https://")):
            continue
        try:
            proxies = _fetch_proxies_from_url(url)
            for proxy in proxies:
                name = proxy.get("name")
                if name:
                    original_map[name] = proxy
        except Exception as e:
            print(f"  ⚠️  获取原始proxies失败 ({url}): {e}")
            continue
    return original_map


def restore_proxies(dst_path: str, sub_urls: list) -> bool:
    try:
        original_map = _collect_original_proxies(sub_urls)
        if not original_map:
            print("  ⚠️  未从sub_urls中获取到有效proxies，跳过还原")
            return False

        with open(dst_path, "r", encoding="utf-8") as f:
            output_data = yaml.safe_load(f)

        if not isinstance(output_data, dict):
            print("  ⚠️  输出文件格式异常，跳过还原")
            return False

        if "proxies" not in output_data:
            print("  ⚠️  输出文件中没有proxies字段，跳过还原")
            return False

        replaced_count = 0
        for i, proxy in enumerate(output_data["proxies"]):
            name = proxy.get("name")
            if name and name in original_map:
                output_data["proxies"][i] = original_map[name]
                replaced_count += 1

        if replaced_count == 0:
            print("  ⚠️  输出文件中没有匹配的proxy name，跳过还原")
            return False

        with open(dst_path, "w", encoding="utf-8") as f:
            yaml.dump(
                output_data,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
                width=4096,
            )

        print(
            f"  ✅ 已还原 {replaced_count} 个proxies (共收集 {len(original_map)} 个原始proxy)"
        )
        return True

    except Exception as e:
        print(f"  ⚠️  还原proxies失败: {e}")
        return False
