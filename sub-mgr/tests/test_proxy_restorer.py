from unittest.mock import Mock, call

import pytest
import requests
import yaml

from sub_mgr.core.proxy_restorer import restore_proxies


@pytest.fixture
def fetch(monkeypatch):
    request = Mock()
    monkeypatch.setattr("sub_mgr.core.proxy_restorer.requests.get", request)
    return request


def subscription_response(proxies):
    return Mock(text=yaml.safe_dump({"proxies": proxies}))


def test_restore_replaces_by_name_and_preserves_other_configuration(tmp_path, fetch):
    original = {
        "name": "香港节点",
        "type": "ss",
        "server": "original.example.com",
        "port": 443,
        "cipher": "aes-128-gcm",
        "password": "test-password",
    }
    unmatched = {"name": "local", "type": "direct"}
    output = {
        "mode": "rule",
        "proxies": [
            unmatched,
            {"name": "香港节点", "server": "converted.example.com", "udp": False},
        ],
        "proxy-groups": [{"name": "select", "type": "select", "proxies": ["香港节点"]}],
        "rules": ["MATCH,select"],
    }
    path = tmp_path / "clash.yaml"
    path.write_text(yaml.safe_dump(output), encoding="utf-8")
    fetch.return_value = subscription_response([original])

    assert restore_proxies(str(path), ["https://provider.example.com/sub"]) is True

    expected = {**output, "proxies": [unmatched, original]}
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == expected
    fetch.return_value.raise_for_status.assert_called_once_with()


def test_restore_uses_last_duplicate_and_skips_invalid_or_failed_sources(
    tmp_path, fetch
):
    first = {"name": "shared", "server": "first.example.com"}
    last = {"name": "shared", "server": "last.example.com"}
    path = tmp_path / "clash.yaml"
    path.write_text("proxies:\n  - name: shared\n", encoding="utf-8")
    fetch.side_effect = [
        requests.ConnectionError("offline"),
        subscription_response([first]),
        subscription_response([last, {"server": "nameless.example.com"}]),
    ]
    valid_urls = [
        "https://offline.example.com/sub",
        "http://first.example.com/sub",
        "https://last.example.com/sub",
    ]

    assert restore_proxies(str(path), ["file:///ignored", "ss://ignored", *valid_urls])

    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {"proxies": [last]}
    assert fetch.call_args_list == [
        call(url, headers={"User-Agent": "mihomo"}, timeout=30) for url in valid_urls
    ]


def test_restore_without_matching_names_keeps_original_file(tmp_path, fetch):
    path = tmp_path / "clash.yaml"
    original = b"# Preserve this comment\nproxies:\n  - name: unmatched\n"
    path.write_bytes(original)
    fetch.return_value = subscription_response([{"name": "remote"}])

    assert restore_proxies(str(path), ["https://provider.example.com/sub"]) is False
    assert path.read_bytes() == original


@pytest.mark.parametrize("response_text", ["proxies: []\n", "rules: []\n", "- item\n"])
def test_restore_without_original_proxies_keeps_file(tmp_path, fetch, response_text):
    path = tmp_path / "clash.yaml"
    original = b"# Preserve this comment\nproxies:\n  - name: local\n"
    path.write_bytes(original)
    fetch.return_value = Mock(text=response_text)

    assert restore_proxies(str(path), ["https://provider.example.com/sub"]) is False
    assert path.read_bytes() == original


def test_restore_rejects_http_error_without_changing_output(tmp_path, fetch):
    path = tmp_path / "clash.yaml"
    original = b"proxies:\n  - name: shared\n"
    path.write_bytes(original)
    response = subscription_response([{"name": "shared", "server": "rejected"}])
    response.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
    fetch.return_value = response

    assert restore_proxies(str(path), ["https://provider.example.com/sub"]) is False
    assert path.read_bytes() == original


@pytest.mark.parametrize("output", [b"proxies: [", b"- item\n", b"rules: []\n"])
def test_restore_rejects_invalid_output_without_modifying_it(tmp_path, fetch, output):
    path = tmp_path / "clash.yaml"
    path.write_bytes(output)
    fetch.return_value = subscription_response([{"name": "remote"}])

    assert restore_proxies(str(path), ["https://provider.example.com/sub"]) is False
    assert path.read_bytes() == output


def test_restore_missing_output_returns_false_without_creating_file(tmp_path, fetch):
    path = tmp_path / "missing.yaml"
    fetch.return_value = subscription_response([{"name": "remote"}])

    assert restore_proxies(str(path), ["https://provider.example.com/sub"]) is False
    assert not path.exists()
