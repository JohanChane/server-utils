import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from acme_cf.removal import RemovalError, cmd_remove


@pytest.fixture
def environment(tmp_path, monkeypatch):
    domain = "example.com"
    acme = tmp_path / "bin" / "acme.sh"
    acme.parent.mkdir()
    acme.write_text("#!/bin/sh\n", encoding="utf-8")
    acme.chmod(0o755)
    certificate_home = tmp_path / "custom-certificates"
    deployed = tmp_path / "ssl" / domain
    deployed.mkdir(parents=True)
    for name in ("private.pem", "fullchain.pem"):
        (deployed / name).write_text(name, encoding="utf-8")
    config = {
        "acme_script": str(acme),
        "ssl_path": str(deployed.parent),
        "domains": [domain, {"domain": "other.example.com", "reload_cmd": "false"}],
        "reload_cmd": "this-command-must-not-run",
    }
    config_path = tmp_path / "config.jsonc"
    config_path.write_text(
        "// Keep this comment\n" + json.dumps(config), encoding="utf-8"
    )
    state = SimpleNamespace(
        domain=domain,
        acme=acme,
        config=config,
        config_path=config_path,
        deployed=deployed,
        paths={
            "rsa": certificate_home / domain / f"{domain}.conf",
            "ecc": certificate_home / f"{domain}_ecc" / f"{domain}.conf",
        },
        info_status=0,
        remove_status=0,
        info_output=None,
        rename_on_remove=True,
    )

    def run(command, **kwargs):
        assert command[0] == state.config["acme_script"]
        assert command[command.index("-d") + 1] == state.domain
        if "--ecc" in command:
            kind = "ecc"
        else:
            assert command[command.index("--keylength") + 1] == "2048"
            kind = "rsa"
        configuration = state.paths[kind]
        if "--info" in command:
            output = state.info_output
            if output is None:
                output = f"DOMAIN_CONF={configuration}\nLe_Domain='{state.domain}'\n"
            return subprocess.CompletedProcess(
                command, state.info_status, stdout=output, stderr=""
            )
        assert "--remove" in command
        if state.remove_status == 0 and state.rename_on_remove:
            configuration.rename(configuration.with_suffix(".conf.removed"))
        return subprocess.CompletedProcess(
            command, state.remove_status, stdout="", stderr=""
        )

    state.run = Mock(side_effect=run)
    monkeypatch.setattr("acme_cf.removal.subprocess.run", state.run)
    return state


def issue(environment, kind="rsa", *, removed=False):
    configuration = environment.paths[kind]
    configuration.parent.mkdir(parents=True)
    record = configuration.with_suffix(".conf.removed") if removed else configuration
    record.write_text(f"Le_Domain='{environment.domain}'\n", encoding="utf-8")
    (configuration.parent / f"{environment.domain}.key").write_text(
        "private key", encoding="utf-8"
    )
    (configuration.parent / f"{environment.domain}.cer").write_text(
        "certificate", encoding="utf-8"
    )
    return configuration


def removal_calls(environment):
    return [
        invocation.args[0]
        for invocation in environment.run.call_args_list
        if "--remove" in invocation.args[0]
    ]


@pytest.mark.parametrize("kind", ["rsa", "ecc"])
def test_remove_discovers_custom_certificate_home_and_preserves_files(
    environment, kind
):
    configuration = issue(environment, kind)
    original_config = copy.deepcopy(environment.config)
    original_bytes = environment.config_path.read_bytes()

    cmd_remove(
        environment.config, environment.domain, config_path=environment.config_path
    )

    assert not configuration.exists()
    assert configuration.with_suffix(".conf.removed").is_file()
    assert (configuration.parent / f"{environment.domain}.key").is_file()
    assert (environment.deployed / "private.pem").is_file()
    assert (environment.deployed / "fullchain.pem").is_file()
    assert environment.config == original_config
    assert environment.config_path.read_bytes() == original_bytes
    commands = removal_calls(environment)
    assert len(commands) == 1
    assert ("--ecc" in commands[0]) is (kind == "ecc")


@pytest.mark.parametrize("keep_extra_file", [False, True])
def test_purge_removes_only_certificate_files_and_preserves_config(
    environment, keep_extra_file
):
    configuration = issue(environment)
    extra = environment.deployed / "README.txt"
    if keep_extra_file:
        extra.write_text("keep this file", encoding="utf-8")
    original_config = copy.deepcopy(environment.config)
    original_bytes = environment.config_path.read_bytes()

    cmd_remove(
        environment.config,
        environment.domain,
        purge=True,
        config_path=environment.config_path,
    )

    assert not configuration.parent.exists()
    assert not (environment.deployed / "private.pem").exists()
    assert not (environment.deployed / "fullchain.pem").exists()
    assert environment.deployed.exists() is keep_extra_file
    if keep_extra_file:
        assert extra.read_text(encoding="utf-8") == "keep this file"
    assert environment.config == original_config
    assert environment.config_path.read_bytes() == original_bytes
    assert len(removal_calls(environment)) == 1


@pytest.mark.parametrize("purge", [False, True])
def test_dry_run_only_queries_and_reports_paths(environment, purge, capsys):
    configuration = issue(environment)

    cmd_remove(environment.config, environment.domain, purge=purge, dry_run=True)

    assert configuration.is_file()
    assert (environment.deployed / "private.pem").is_file()
    assert removal_calls(environment) == []
    output = capsys.readouterr().out
    assert environment.domain in output
    if purge:
        assert str(configuration.parent) in output
        assert str(environment.deployed / "private.pem") in output


def test_already_removed_certificate_can_be_purged(environment):
    configuration = issue(environment, removed=True)

    cmd_remove(environment.config, environment.domain, purge=True)

    assert not configuration.parent.exists()
    assert not environment.deployed.exists()
    assert removal_calls(environment) == []


@pytest.mark.parametrize("operation", ["info", "remove"])
def test_acme_failure_prevents_deleting_files(environment, operation):
    configuration = issue(environment)
    setattr(environment, f"{operation}_status", 1)

    with pytest.raises((RemovalError, ValueError, OSError)):
        cmd_remove(environment.config, environment.domain, purge=True)

    assert configuration.is_file()
    assert (environment.deployed / "private.pem").is_file()
    assert (environment.deployed / "fullchain.pem").is_file()
    if operation == "info":
        assert removal_calls(environment) == []


def test_success_exit_without_stopped_renewal_does_not_purge(environment):
    configuration = issue(environment)
    environment.rename_on_remove = False

    with pytest.raises((RemovalError, ValueError, OSError)):
        cmd_remove(environment.config, environment.domain, purge=True)

    assert configuration.is_file()
    assert (environment.deployed / "private.pem").is_file()


def test_unknown_certificate_does_not_delete_deployed_files(environment):
    with pytest.raises((RemovalError, ValueError, OSError)):
        cmd_remove(environment.config, environment.domain, purge=True)

    assert (environment.deployed / "private.pem").is_file()
    assert removal_calls(environment) == []


@pytest.mark.parametrize(
    "domain", ["", "..", "../other", "/tmp/other", "x/y", "x\\y", "x\ny"]
)
def test_unsafe_domain_is_rejected_before_calling_acme(environment, domain):
    with pytest.raises((RemovalError, ValueError)):
        cmd_remove(environment.config, domain, purge=True)

    environment.run.assert_not_called()


def test_two_certificate_types_require_explicit_selection(environment):
    rsa_configuration = issue(environment, "rsa")
    ecc_configuration = issue(environment, "ecc")

    with pytest.raises((RemovalError, ValueError)):
        cmd_remove(environment.config, environment.domain)

    assert rsa_configuration.is_file()
    assert ecc_configuration.is_file()
    assert removal_calls(environment) == []


@pytest.mark.parametrize("kind", ["rsa", "ecc"])
def test_explicit_selection_stops_only_selected_certificate(environment, kind):
    configurations = {name: issue(environment, name) for name in ("rsa", "ecc")}

    cmd_remove(environment.config, environment.domain, **{kind: True})

    other = "rsa" if kind == "ecc" else "ecc"
    assert not configurations[kind].exists()
    assert configurations[kind].with_suffix(".conf.removed").is_file()
    assert configurations[other].is_file()
    assert len(removal_calls(environment)) == 1


@pytest.mark.parametrize("kind", ["rsa", "ecc"])
def test_purge_refuses_shared_deployment_while_other_certificate_is_active(
    environment, kind
):
    configurations = [issue(environment, name) for name in ("rsa", "ecc")]

    with pytest.raises((RemovalError, ValueError)):
        cmd_remove(environment.config, environment.domain, purge=True, **{kind: True})

    assert all(configuration.is_file() for configuration in configurations)
    assert (environment.deployed / "private.pem").is_file()
    assert removal_calls(environment) == []


@pytest.mark.parametrize(
    "target", ["certificate_directory", "record", "deployed_directory", "deployed_file"]
)
def test_purge_rejects_symlinks_without_removing_their_targets(
    environment, tmp_path, target
):
    configuration = issue(environment)
    paths = {
        "certificate_directory": configuration.parent,
        "record": configuration,
        "deployed_directory": environment.deployed,
        "deployed_file": environment.deployed / "private.pem",
    }
    path = paths[target]
    external = tmp_path / "external"
    path.rename(external)
    path.symlink_to(external, target_is_directory=external.is_dir())

    with pytest.raises((RemovalError, ValueError, OSError)):
        cmd_remove(environment.config, environment.domain, purge=True)

    assert external.exists()
    assert path.is_symlink()
    assert removal_calls(environment) == []


def test_purge_rejects_overlapping_certificate_and_deployment_directories(environment):
    configuration = issue(environment)
    environment.config["ssl_path"] = str(configuration.parent.parent)

    with pytest.raises((RemovalError, ValueError)):
        cmd_remove(environment.config, environment.domain, purge=True)

    assert configuration.is_file()
    assert removal_calls(environment) == []


@pytest.mark.parametrize(
    "output",
    [
        "Le_Domain=example.com\n",
        "DOMAIN_CONF=example.com/example.com.conf\n",
        "DOMAIN_CONF=/tmp/unrelated/example.com.conf\n",
    ],
)
def test_unexpected_info_path_is_rejected(environment, output):
    configuration = issue(environment)
    environment.info_output = output

    with pytest.raises((RemovalError, ValueError)):
        cmd_remove(environment.config, environment.domain, purge=True)

    assert configuration.is_file()
    assert (environment.deployed / "private.pem").is_file()
    assert removal_calls(environment) == []


def test_purge_protects_config_file_inside_certificate_directory(environment):
    configuration = issue(environment)
    protected_config = configuration.parent / "config.jsonc"
    protected_config.write_bytes(environment.config_path.read_bytes())
    original_bytes = protected_config.read_bytes()

    with pytest.raises((RemovalError, ValueError)):
        cmd_remove(
            environment.config,
            environment.domain,
            purge=True,
            config_path=protected_config,
        )

    assert protected_config.read_bytes() == original_bytes
    assert configuration.is_file()
    assert removal_calls(environment) == []


def test_deployment_cleanup_failure_keeps_acme_record_for_retry(
    environment, monkeypatch
):
    configuration = issue(environment)
    private_key = environment.deployed / "private.pem"
    original_unlink = Path.unlink

    def fail_private_key_unlink(path, *args, **kwargs):
        if path == private_key:
            raise PermissionError("permission denied")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_private_key_unlink)
    with pytest.raises((RemovalError, OSError)):
        cmd_remove(environment.config, environment.domain, purge=True)

    assert configuration.with_suffix(".conf.removed").is_file()
    assert private_key.is_file()
    monkeypatch.setattr(Path, "unlink", original_unlink)

    cmd_remove(environment.config, environment.domain, purge=True)

    assert not configuration.parent.exists()
    assert not environment.deployed.exists()
    assert len(removal_calls(environment)) == 1


def test_remove_without_purge_does_not_require_installation_settings(environment):
    configuration = issue(environment)
    del environment.config["ssl_path"]

    cmd_remove(environment.config, environment.domain)

    assert configuration.with_suffix(".conf.removed").is_file()
    assert (environment.deployed / "private.pem").is_file()


@pytest.mark.parametrize("kind", ["rsa", "ecc"])
def test_missing_explicit_certificate_does_not_remove_the_other_type(environment, kind):
    other = "rsa" if kind == "ecc" else "ecc"
    configuration = issue(environment, other)

    with pytest.raises((RemovalError, ValueError)):
        cmd_remove(environment.config, environment.domain, **{kind: True})

    assert configuration.is_file()
    assert removal_calls(environment) == []


def test_purge_protects_acme_script_inside_certificate_directory(environment):
    configuration = issue(environment)
    script = configuration.parent / "acme.sh"
    environment.acme.rename(script)
    environment.config["acme_script"] = str(script)

    with pytest.raises((RemovalError, ValueError)):
        cmd_remove(environment.config, environment.domain, purge=True)

    assert script.is_file()
    assert configuration.is_file()
    assert removal_calls(environment) == []


def test_wildcard_domain_is_treated_as_a_literal_directory_name(environment):
    certificate_home = environment.paths["rsa"].parent.parent
    environment.domain = "*.example.com"
    environment.paths = {
        "rsa": certificate_home / environment.domain / f"{environment.domain}.conf",
        "ecc": certificate_home
        / f"{environment.domain}_ecc"
        / f"{environment.domain}.conf",
    }
    wildcard_deployed = environment.deployed.with_name(environment.domain)
    environment.deployed.rename(wildcard_deployed)
    environment.deployed = wildcard_deployed
    configuration = issue(environment)
    sibling = certificate_home / "www.example.com"
    sibling.mkdir()
    (sibling / "private.key").write_text("keep", encoding="utf-8")

    cmd_remove(environment.config, environment.domain, purge=True)

    assert not configuration.parent.exists()
    assert not environment.deployed.exists()
    assert (sibling / "private.key").read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("target", ["config", "script"])
def test_purge_protects_config_and_script_symlinks_inside_certificate_directory(
    environment, target
):
    configuration = issue(environment)
    source = environment.config_path if target == "config" else environment.acme
    link = configuration.parent / source.name
    link.symlink_to(source)
    config_path = environment.config_path
    if target == "config":
        config_path = link
    else:
        environment.config["acme_script"] = str(link)

    with pytest.raises((RemovalError, ValueError)):
        cmd_remove(
            environment.config,
            environment.domain,
            purge=True,
            config_path=config_path,
        )

    assert link.is_symlink()
    assert source.is_file()
    assert configuration.is_file()
    assert removal_calls(environment) == []


def test_purge_rechecks_other_certificate_after_stopping_renewal(environment):
    configuration = issue(environment)
    original_run = environment.run.side_effect

    def run_with_concurrent_certificate(command, **kwargs):
        result = original_run(command, **kwargs)
        if "--remove" in command:
            issue(environment, "ecc")
        return result

    environment.run.side_effect = run_with_concurrent_certificate
    with pytest.raises((RemovalError, ValueError)):
        cmd_remove(environment.config, environment.domain, purge=True)

    assert configuration.with_suffix(".conf.removed").is_file()
    assert environment.paths["ecc"].is_file()
    assert (environment.deployed / "private.pem").is_file()
    assert (environment.deployed / "fullchain.pem").is_file()
