from unittest.mock import Mock, call
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from sub_mgr.core import sub_mgr as converter_module
from sub_mgr.core.sub_mgr import (
    SubscriptionConverter,
    load_config_from_toml,
    save_config_to_toml,
)


@pytest.fixture
def converter():
    return SubscriptionConverter(
        base_url="https://converter.example.com/sub",
        config_url="https://rules.example.com/config.ini?name=default&version=2",
        opts={"target": "clash", "udp": True, "list": False},
    )


def test_conversion_url_preserves_urls_and_merges_options(converter):
    urls = [
        "https://provider.example.com/sub?token=a+b&name=香港",
        "https://backup.example.com/sub?token=x%2Fy",
    ]
    append_options = {"target": "surge", "udp": True, "list": True}
    subscription_options = {"udp": False}

    result = urlsplit(
        converter.build_conversion_url(urls, subscription_options, append_options)
    )
    query = parse_qs(result.query)

    assert (result.scheme, result.netloc, result.path) == (
        "https",
        "converter.example.com",
        "/sub",
    )
    assert query["url"] == ["|".join(urls)]
    assert query["config"] == [converter.config_url]
    assert query["target"] == ["surge"]
    assert query["udp"] == ["false"]
    assert query["list"] == ["true"]
    assert converter.opts == {"target": "clash", "udp": True, "list": False}
    assert append_options == {"target": "surge", "udp": True, "list": True}
    assert subscription_options == {"udp": False}


def test_conversion_writes_response_and_creates_parent_directories(
    converter, tmp_path, monkeypatch
):
    content = "proxies:\n  - name: 香港\n".encode()
    response = Mock(content=content)
    get = Mock(return_value=response)
    monkeypatch.setattr(converter_module.requests, "get", get)
    destination = tmp_path / "nested" / "clash.yaml"
    urls = ["https://provider.example.com/sub"]

    assert converter.convert_subscription(urls, str(destination)) is True

    assert destination.read_bytes() == content
    get.assert_called_once()
    assert get.call_args.args[0] == converter.build_conversion_url(urls)
    assert get.call_args.kwargs["timeout"] == 60
    response.raise_for_status.assert_called_once_with()


@pytest.mark.parametrize("failure", ["empty", "network", "http"])
def test_failed_conversion_preserves_existing_file(
    converter, tmp_path, monkeypatch, failure
):
    destination = tmp_path / "clash.yaml"
    destination.write_bytes(b"existing configuration\n")
    response = Mock(content=b"" if failure == "empty" else b"error response")
    get = Mock(return_value=response)
    if failure == "network":
        get.side_effect = requests.exceptions.Timeout("request timed out")
    elif failure == "http":
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "HTTP 500"
        )
    monkeypatch.setattr(converter_module.requests, "get", get)

    assert (
        converter.convert_subscription(
            ["https://provider.example.com/sub"], str(destination)
        )
        is False
    )

    get.assert_called_once()
    assert destination.read_bytes() == b"existing configuration\n"


def test_batch_skips_invalid_entries_and_restores_only_successful_conversions(
    converter, tmp_path, monkeypatch
):
    urls = ["https://provider.example.com/sub"]
    absolute_destination = str(tmp_path / "absolute.yaml")
    output_directory = tmp_path / "out"
    subscriptions = [
        {"enable": False, "sub_urls": urls, "dst_path": "disabled.yaml"},
        {"sub_urls": [], "dst_path": "missing-urls.yaml"},
        {"sub_urls": urls},
        {
            "sub_urls": urls,
            "dst_path": "nested/success.yaml",
            "opts": {"target": "surge"},
            "append_opts": {"udp": False},
        },
        {"sub_urls": urls, "dst_path": absolute_destination},
    ]
    convert = Mock(side_effect=[True, False])
    restore = Mock()
    monkeypatch.setattr(converter, "convert_subscription", convert)
    monkeypatch.setattr(converter_module, "restore_proxies", restore)
    monkeypatch.setattr(converter_module.time, "sleep", Mock())

    results = converter.batch_convert(subscriptions, str(output_directory))

    successful_destination = str(output_directory / "nested" / "success.yaml")
    assert results == {successful_destination: True, absolute_destination: False}
    assert convert.call_args_list == [
        call(
            urls,
            successful_destination,
            subscription_opts={"target": "surge"},
            append_opts={"udp": False},
        ),
        call(urls, absolute_destination, subscription_opts=None, append_opts=None),
    ]
    restore.assert_called_once_with(successful_destination, urls)


def test_toml_config_round_trip_creates_parent_directories(tmp_path):
    destination = tmp_path / "nested" / "config.toml"
    config = {
        "settings": {"location": "https://example.com/sub/"},
        "subscriptions": [
            {
                "name": "香港订阅",
                "enable": True,
                "sub_urls": ["https://provider.example.com/sub"],
                "dst_path": "clash.yaml",
            }
        ],
    }

    save_config_to_toml(config, str(destination))

    assert destination.is_file()
    assert load_config_from_toml(str(destination)) == config


@pytest.mark.parametrize("exists", [False, True], ids=["missing", "invalid"])
def test_missing_or_invalid_toml_returns_empty_config(tmp_path, exists):
    source = tmp_path / "config.toml"
    if exists:
        source.write_text("[invalid TOML", encoding="utf-8")

    assert load_config_from_toml(str(source)) == {}
