from unittest.mock import Mock

import pytest

from sub_mgr import cli
from sub_mgr import sub_mgr as manager_module


@pytest.mark.parametrize(
    ("arguments", "jobs"),
    [([], 1), (["-j", "4"], 4), (["--jobs", "3"], 3)],
)
def test_convert_cli_passes_jobs_and_existing_options(monkeypatch, arguments, jobs):
    convert = Mock()
    monkeypatch.setattr(cli, "convert_subscriptions", convert)
    monkeypatch.setattr(
        "sys.argv",
        [
            "sub-mgr",
            "-c",
            "custom.toml",
            "convert",
            "--out-dir",
            "converted",
            "--name",
            "selected",
            *arguments,
        ],
    )

    cli.main()

    convert.assert_called_once_with("custom.toml", "converted", "selected", jobs=jobs)


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "invalid"])
def test_convert_cli_rejects_invalid_jobs_before_conversion(monkeypatch, capsys, value):
    convert = Mock()
    monkeypatch.setattr(cli, "convert_subscriptions", convert)
    monkeypatch.setattr("sys.argv", ["sub-mgr", "convert", "--jobs", value])

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    assert "jobs 必须为正整数" in capsys.readouterr().err
    convert.assert_not_called()


def test_convert_cli_reports_batch_configuration_errors(monkeypatch, capsys):
    convert = Mock(side_effect=ValueError("重复输出路径: shared.yaml"))
    monkeypatch.setattr(cli, "convert_subscriptions", convert)
    monkeypatch.setattr("sys.argv", ["sub-mgr", "convert", "-j", "2"])

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 2
    output = capsys.readouterr()
    assert "重复输出路径: shared.yaml" in output.err
    assert "Traceback" not in output.err


@pytest.mark.parametrize(
    ("results", "counts"),
    [
        ({"first.yaml": True, "second.yaml": False}, "成功 1，失败 1，跳过 2"),
        ({}, "成功 0，失败 0，跳过 4"),
    ],
)
def test_conversion_summary_counts_attempted_and_skipped_subscriptions(
    monkeypatch, tmp_path, capsys, results, counts
):
    subscriptions = [
        {"name": "first", "dst_path": "first.yaml", "sub_urls": ["https://a.example"]},
        {
            "name": "second",
            "dst_path": "second.yaml",
            "sub_urls": ["https://b.example"],
        },
        {"name": "disabled", "enable": False},
        {"name": "invalid", "sub_urls": []},
    ]
    converter = Mock(base_url="https://converter.example", config_url="rules", opts={})
    converter.batch_convert.return_value = results
    monkeypatch.setattr(
        manager_module,
        "load_config_from_toml",
        Mock(return_value={"subscriptions": subscriptions}),
    )
    monkeypatch.setattr(
        manager_module, "SubscriptionConverter", Mock(return_value=converter)
    )

    manager_module.convert_subscriptions("test.toml", str(tmp_path), None, jobs=3)

    converter.batch_convert.assert_called_once_with(
        subscriptions, str(tmp_path), jobs=3
    )
    output = capsys.readouterr().out
    assert counts in output
    if results:
        assert output.index("first.yaml: ✅ 成功") < output.index(
            "second.yaml: ❌ 失败"
        )
