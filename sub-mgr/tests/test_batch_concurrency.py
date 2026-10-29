from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, Lock, get_ident
from unittest.mock import Mock, call

import pytest

from sub_mgr.core import sub_mgr as converter_module
from sub_mgr.core.sub_mgr import SubscriptionConverter


def subscription(name, **overrides):
    return {
        "name": name,
        "sub_urls": [f"https://provider.example.com/{name}"],
        "dst_path": f"{name}.yaml",
        **overrides,
    }


@pytest.fixture
def converter():
    return SubscriptionConverter()


def test_jobs_limit_covers_conversion_and_restoration(converter, tmp_path, monkeypatch):
    lock = Lock()
    restoring_pair = Barrier(2)
    active = 0
    peak = 0
    conversion_threads = {}
    restoration_threads = {}

    def convert(urls, destination, *, emit, **options):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            conversion_threads[destination] = get_ident()
        emit(f"converted {destination}")
        return True

    def restore(destination, urls, *, emit):
        nonlocal active
        restoration_threads[destination] = get_ident()
        restoring_pair.wait(timeout=5)
        with lock:
            active -= 1
        emit(f"restored {destination}")
        return True

    sleep = Mock()
    monkeypatch.setattr(converter, "convert_subscription", convert)
    monkeypatch.setattr(converter_module, "restore_proxies", restore)
    monkeypatch.setattr(converter_module.time, "sleep", sleep)
    subscriptions = [subscription(f"item-{number}") for number in range(6)]

    results = converter.batch_convert(subscriptions, str(tmp_path), jobs=2)

    assert len(results) == 6
    assert all(results.values())
    assert peak == 2
    assert active == 0
    assert conversion_threads == restoration_threads
    sleep.assert_not_called()


def test_completed_task_prints_before_slow_task_and_keeps_log_blocks_together(
    converter, tmp_path, monkeypatch, capsys
):
    slow_started = Event()
    release_slow = Event()
    fast_printed = Event()
    chunks = []
    output_threads = []
    caller_threads = []

    def output(*parts, **options):
        text = options.get("sep", " ").join(str(part) for part in parts)
        chunks.append((text, options))
        output_threads.append(get_ident())
        if "<<fast:restored>>" in text:
            fast_printed.set()

    def convert(urls, destination, *, emit, **options):
        name = Path(destination).stem
        emit(f"<<{name}:start>>")
        if name == "slow":
            slow_started.set()
            assert release_slow.wait(timeout=10)
        else:
            assert slow_started.wait(timeout=5)
        emit(f"<<{name}:end>>")
        return True

    def restore(destination, urls, *, emit):
        emit(f"<<{Path(destination).stem}:restored>>")
        return True

    def run_batch():
        caller_threads.append(get_ident())
        return converter.batch_convert(
            [subscription("slow"), subscription("fast")], str(tmp_path), jobs=2
        )

    monkeypatch.setattr(converter, "convert_subscription", convert)
    monkeypatch.setattr(converter_module, "restore_proxies", restore)
    monkeypatch.setattr(converter_module, "print", output, raising=False)
    with ThreadPoolExecutor(max_workers=1) as caller:
        future = caller.submit(run_batch)
        try:
            assert fast_printed.wait(timeout=5)
            assert not future.done()
            assert not any("<<slow:" in text for text, _ in chunks)
        finally:
            release_slow.set()
        results = future.result(timeout=5)

    blocks = [(text, options) for text, options in chunks if "<<" in text]
    assert len(blocks) == 2
    for (text, options), name in zip(blocks, ["fast", "slow"], strict=True):
        markers = [f"<<{name}:{stage}>>" for stage in ["start", "end", "restored"]]
        assert all(marker in text for marker in markers)
        assert [text.index(marker) for marker in markers] == sorted(
            text.index(marker) for marker in markers
        )
        assert options.get("flush") is True
    assert set(output_threads) == set(caller_threads)
    assert list(results) == [str(tmp_path / "slow.yaml"), str(tmp_path / "fast.yaml")]
    assert all(results.values())
    assert capsys.readouterr().out == ""


def test_failed_tasks_do_not_stop_batch_or_restore_failed_conversions(
    converter, tmp_path, monkeypatch, capsys
):
    restored = []

    def convert(urls, destination, *, emit, **options):
        name = Path(destination).stem
        if name == "raises":
            raise RuntimeError("conversion exploded")
        return name != "failed"

    def restore(destination, urls, *, emit):
        name = Path(destination).stem
        restored.append(name)
        if name == "restore-error":
            raise RuntimeError("restoration exploded")
        emit("restoration complete")
        return True

    monkeypatch.setattr(converter, "convert_subscription", convert)
    monkeypatch.setattr(converter_module, "restore_proxies", restore)
    names = ["raises", "failed", "restore-error", "success"]

    results = converter.batch_convert(
        [subscription(name) for name in names], str(tmp_path), jobs=2
    )

    assert list(results.items()) == [
        (str(tmp_path / f"{name}.yaml"), success)
        for name, success in zip(names, [False, False, True, True], strict=True)
    ]
    assert sorted(restored) == ["restore-error", "success"]
    output = capsys.readouterr().out
    assert "conversion exploded" in output
    assert "restoration exploded" in output
    assert "restoration complete" in output


@pytest.mark.parametrize("jobs", [1, 2])
@pytest.mark.parametrize("alias", ["normalized", "absolute", "symlink"])
def test_duplicate_targets_are_rejected_before_any_task_starts(
    converter, tmp_path, monkeypatch, alias, jobs
):
    directory = tmp_path / "out"
    directory.mkdir()
    if alias == "normalized":
        duplicate = "nested/../same.yaml"
    elif alias == "absolute":
        duplicate = str(directory / "same.yaml")
    else:
        link = tmp_path / "alias"
        link.symlink_to(directory, target_is_directory=True)
        duplicate = str(link / "same.yaml")
    convert = Mock(return_value=True)
    restore = Mock(return_value=True)
    monkeypatch.setattr(converter, "convert_subscription", convert)
    monkeypatch.setattr(converter_module, "restore_proxies", restore)

    with pytest.raises(ValueError):
        converter.batch_convert(
            [
                subscription("unrelated"),
                subscription("first", dst_path="same.yaml"),
                subscription("second", dst_path=duplicate),
            ],
            str(directory),
            jobs=jobs,
        )

    convert.assert_not_called()
    restore.assert_not_called()
    assert not (directory / "unrelated.yaml").exists()


@pytest.mark.parametrize("jobs", [0, -1, 1.5, "2"])
def test_jobs_requires_a_positive_integer(converter, tmp_path, monkeypatch, jobs):
    convert = Mock()
    monkeypatch.setattr(converter, "convert_subscription", convert)

    with pytest.raises(ValueError):
        converter.batch_convert([subscription("one")], str(tmp_path), jobs=jobs)

    convert.assert_not_called()


@pytest.mark.parametrize("jobs", [None, 1])
def test_serial_mode_finishes_restoration_before_next_conversion(
    converter, tmp_path, monkeypatch, jobs
):
    events = []

    def convert(urls, destination, *, emit, **options):
        events.append(("convert", Path(destination).stem))
        return True

    def restore(destination, urls, *, emit):
        events.append(("restore", Path(destination).stem))
        return True

    sleep = Mock(side_effect=lambda duration: events.append(("sleep", duration)))
    monkeypatch.setattr(converter, "convert_subscription", convert)
    monkeypatch.setattr(converter_module, "restore_proxies", restore)
    monkeypatch.setattr(converter_module.time, "sleep", sleep)
    options = {} if jobs is None else {"jobs": jobs}

    results = converter.batch_convert(
        [subscription("one"), subscription("two")], str(tmp_path), **options
    )

    assert events == [
        ("convert", "one"),
        ("restore", "one"),
        ("sleep", 2),
        ("convert", "two"),
        ("restore", "two"),
    ]
    assert sleep.call_args_list == [call(2)]
    assert list(results.values()) == [True, True]


@pytest.mark.parametrize(
    "subscriptions",
    [
        [],
        [subscription("disabled", enable=False), subscription("invalid", sub_urls=[])],
    ],
)
def test_parallel_batch_with_no_valid_tasks_returns_empty_results(
    converter, tmp_path, monkeypatch, subscriptions
):
    convert = Mock()
    monkeypatch.setattr(converter, "convert_subscription", convert)

    assert converter.batch_convert(subscriptions, str(tmp_path), jobs=4) == {}

    convert.assert_not_called()
