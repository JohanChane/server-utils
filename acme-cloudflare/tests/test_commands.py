import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import call, patch

from acme_cf.commands import cmd_apply, cmd_check, cmd_install


class DomainConfigTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = Path(temporary_directory.name)
        self.acme = self.root / "acme.sh"
        self.acme.touch()
        self.default_reload = "sudo systemctl reload nginx"
        self.custom_reload = "sudo nginx -t && sudo systemctl reload nginx-custom"
        self.domains = [
            "legacy.example.com",
            {"domain": "custom.example.com", "reload_cmd": self.custom_reload},
            {"domain": "inherited.example.com"},
            {"domain": "disabled.example.com", "reload_cmd": ""},
        ]
        self.domain_names = [
            "legacy.example.com",
            "custom.example.com",
            "inherited.example.com",
            "disabled.example.com",
        ]
        self.config = {
            "acme_script": str(self.acme),
            "ssl_path": str(self.root),
            "reload_cmd": self.default_reload,
            "cloudflare": {"dns_token": "test-token", "account_id": "test-account"},
            "domains": self.domains,
        }

    def test_install_selects_reload_command_per_domain(self):
        reload_commands = [
            self.default_reload,
            self.custom_reload,
            self.default_reload,
            "",
        ]
        with (
            patch("acme_cf.commands.subprocess.run") as run,
            redirect_stdout(io.StringIO()),
        ):
            cmd_install(self.config)

        expected_commands = []
        for domain, reload_command in zip(self.domain_names, reload_commands):
            directory = self.root / domain
            self.assertTrue(directory.is_dir())
            expected_commands.extend(
                [
                    [
                        str(self.acme),
                        "--install-cert",
                        "-d",
                        domain,
                        "--key-file",
                        str(directory / "private.pem"),
                        "--fullchain-file",
                        str(directory / "fullchain.pem"),
                        "--reloadcmd",
                        reload_command,
                    ],
                    [str(self.acme), "--info", "-d", domain],
                ]
            )
        self.assertEqual(
            [invocation.args[0] for invocation in run.call_args_list], expected_commands
        )

    def test_apply_accepts_mixed_domain_entries(self):
        for force in (False, True):
            with self.subTest(force=force):
                result = subprocess.CompletedProcess([], 0)
                with (
                    patch(
                        "acme_cf.commands.subprocess.run", return_value=result
                    ) as run,
                    redirect_stdout(io.StringIO()),
                ):
                    cmd_apply(self.config, force=force)

                expected_commands = [
                    [str(self.acme), "--issue", "-d", domain, "--dns", "dns_cf"]
                    + (["--force"] if force else [])
                    for domain in self.domain_names
                ]
                expected_commands.append([str(self.acme), "--list"])
                self.assertEqual(
                    [invocation.args[0] for invocation in run.call_args_list],
                    expected_commands,
                )
                for invocation in run.call_args_list[:-1]:
                    self.assertEqual(invocation.kwargs["env"]["CF_Token"], "test-token")
                    self.assertEqual(
                        invocation.kwargs["env"]["CF_Account_ID"], "test-account"
                    )

    def test_check_accepts_mixed_domain_entries(self):
        certificate = "test certificate output"
        result = subprocess.CompletedProcess([], 0, stdout=certificate)
        with (
            patch("acme_cf.commands.subprocess.run", return_value=result) as run,
            redirect_stdout(io.StringIO()),
        ):
            cmd_check(self.config)

        expected_calls = []
        for domain in self.domain_names:
            expected_calls.extend(
                [
                    call(
                        [
                            "openssl",
                            "s_client",
                            "-servername",
                            domain,
                            "-connect",
                            f"{domain}:443",
                        ],
                        input="",
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    ),
                    call(
                        ["openssl", "x509", "-noout", "-dates"],
                        input=certificate,
                        capture_output=False,
                        text=True,
                        check=False,
                    ),
                ]
            )
        self.assertEqual(run.call_args_list, expected_calls)


if __name__ == "__main__":
    unittest.main()
