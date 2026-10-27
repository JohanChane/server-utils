import os
import subprocess
import sys
from pathlib import Path

from acme_cf.config import iter_domains


def _run(
    cmd: list[str], env: dict | None = None, capture: bool = False
) -> subprocess.CompletedProcess:
    merged_env = None
    if env is not None:
        merged_env = {**os.environ, **env}
    return subprocess.run(
        cmd, env=merged_env, capture_output=capture, text=True, check=False
    )


def cmd_apply(config: dict, force: bool = False) -> None:
    acme = config["acme_script"]
    if not Path(acme).exists():
        print(f"Error: acme.sh not found at {acme}", file=sys.stderr)
        sys.exit(1)

    cf = config["cloudflare"]
    env = {
        "CF_Token": cf["dns_token"],
        "CF_Account_ID": cf["account_id"],
    }

    for domain, _ in iter_domains(config):
        print(f"Issuing cert: {domain}")

        cmd = [acme, "--issue", "-d", domain, "--dns", "dns_cf"]
        if force:
            cmd.append("--force")

        result = _run(cmd, env=env)
        if result.returncode == 0:
            print(f"OK: {domain}")
        else:
            print(f"FAIL: {domain}", file=sys.stderr)
        print("-" * 40)

    _run([acme, "--list"])


def cmd_install(config: dict) -> None:
    acme = config["acme_script"]
    ssl_path = Path(config["ssl_path"])

    if not ssl_path.exists():
        ssl_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["sudo", "chown", "root:www-data", str(ssl_path)], check=False)
        subprocess.run(["sudo", "chmod", "750", str(ssl_path)], check=False)

    for domain, reload_cmd in iter_domains(config):
        print(f"Installing cert for: {domain}")
        domain_dir = ssl_path / domain
        domain_dir.mkdir(parents=True, exist_ok=True)

        _run(
            [
                acme,
                "--install-cert",
                "-d",
                domain,
                "--key-file",
                str(domain_dir / "private.pem"),
                "--fullchain-file",
                str(domain_dir / "fullchain.pem"),
                "--reloadcmd",
                reload_cmd,
            ]
        )

        _run([acme, "--info", "-d", domain], capture=False)
        print(f"Installed: {ssl_path}/{domain}/")
        print("-" * 40)

    print("All certs installed.")


def cmd_check(config: dict) -> None:
    for domain, _ in iter_domains(config):
        print(f"\n[{domain}]")
        try:
            result = subprocess.run(
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
            )
            if result.stdout:
                subprocess.run(
                    ["openssl", "x509", "-noout", "-dates"],
                    input=result.stdout,
                    capture_output=False,
                    text=True,
                    check=False,
                )
        except subprocess.TimeoutExpired:
            print(f"  timeout connecting to {domain}")
        except FileNotFoundError:
            print("  openssl not found", file=sys.stderr)
            sys.exit(1)


def cmd_refresh(config: dict) -> None:
    p = config["purge"]
    zone_id = p["zone_id"]
    token = p["api_token"]

    result = subprocess.run(
        [
            "curl",
            "-s",
            "-X",
            "POST",
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache",
            "-H",
            f"Authorization: Bearer {token}",
            "-H",
            "Content-Type: application/json",
            "-d",
            '{"purge_everything":true}',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        print(f"curl failed with code {result.returncode}", file=sys.stderr)
        sys.exit(1)


def cmd_list(config: dict) -> None:
    acme = config["acme_script"]
    _run([acme, "--list"])
