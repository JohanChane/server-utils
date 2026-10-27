import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class RemovalError(Exception):
    """The requested certificate cannot be removed safely."""


@dataclass(frozen=True)
class _Certificate:
    conf: Path
    ecc: bool

    @property
    def removed_conf(self) -> Path:
        return self.conf.with_name(self.conf.name + ".removed")

    @property
    def flags(self) -> list[str]:
        # Explicit RSA selection prevents acme.sh from falling back to an ECC cert.
        return ["--ecc"] if self.ecc else ["--keylength", "2048"]

    @property
    def exists(self) -> bool:
        return self.conf.is_file() or self.removed_conf.is_file()


def _check_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise RemovalError(f"Refusing unsafe path: {path}")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise RemovalError(f"Refusing symbolic link: {part}")


def _check_certificate(cert: _Certificate) -> None:
    _check_path(cert.conf)
    _check_path(cert.removed_conf)
    if cert.conf.parent.exists() and not cert.conf.parent.is_dir():
        raise RemovalError(f"Certificate path is not a directory: {cert.conf.parent}")
    for path in (cert.conf, cert.removed_conf):
        if path.exists() and not path.is_file():
            raise RemovalError(f"Certificate config is not a regular file: {path}")


def _discover(acme: str, domain: str, *, ecc: bool) -> _Certificate:
    flags = ["--ecc"] if ecc else ["--keylength", "2048"]
    result = subprocess.run(
        [acme, "--info", "-d", domain, *flags],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RemovalError(
            f"acme.sh --info failed for {domain} (exit {result.returncode})"
        )
    # --info may exit successfully even if the domain config does not exist.
    # Read only the path; never execute or print the returned config contents.
    paths = [
        line.removeprefix("DOMAIN_CONF=")
        for line in result.stdout.splitlines()
        if line.startswith("DOMAIN_CONF=")
    ]
    if len(paths) != 1 or not paths[0]:
        raise RemovalError(f"Cannot determine certificate directory for {domain}")
    conf = Path(paths[0])
    expected_dir = domain + ("_ecc" if ecc else "")
    if conf.name != f"{domain}.conf" or conf.parent.name != expected_dir:
        raise RemovalError(f"Unexpected certificate config path: {conf}")
    cert = _Certificate(conf, ecc)
    _check_certificate(cert)
    return cert


def _check_purge_paths(
    cert: _Certificate, installed_dir: Path, protected: list[Path]
) -> None:
    _check_certificate(cert)
    _check_path(installed_dir)
    if installed_dir.exists() and not installed_dir.is_dir():
        raise RemovalError(
            f"Installed certificate path is not a directory: {installed_dir}"
        )
    cert_dir = cert.conf.parent
    if cert_dir.is_relative_to(installed_dir) or installed_dir.is_relative_to(cert_dir):
        raise RemovalError(
            "Certificate and installed directories overlap; refusing purge"
        )
    installed_files = [
        installed_dir / name for name in ("private.pem", "fullchain.pem")
    ]
    for path in installed_files:
        _check_path(path)
        if path.exists() and not path.is_file():
            raise RemovalError(f"Installed certificate is not a regular file: {path}")
    for path in protected:
        if path.is_relative_to(cert_dir) or path in installed_files:
            raise RemovalError(
                f"Purge would delete the script or configuration: {path}"
            )


def _purge(cert: _Certificate, installed_dir: Path) -> None:
    # Keep the acme.sh removal record until deployed files have been cleaned up,
    # so a permission error there can be retried with --purge.
    for name in ("private.pem", "fullchain.pem"):
        path = installed_dir / name
        if path.exists():
            path.unlink()
            print(f"Deleted: {path}")
    if installed_dir.exists():
        if not any(installed_dir.iterdir()):
            installed_dir.rmdir()
            print(f"Deleted empty directory: {installed_dir}")
        else:
            print(f"Kept directory with other files: {installed_dir}")

    cert_dir = cert.conf.parent
    # Delete the removal marker last to allow retries after partial cleanup.
    for path in cert_dir.iterdir():
        if path == cert.removed_conf:
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    cert.removed_conf.unlink()
    cert_dir.rmdir()
    print(f"Deleted certificate directory: {cert_dir}")


def cmd_remove(
    config: dict,
    domain: str,
    *,
    purge: bool = False,
    dry_run: bool = False,
    ecc: bool = False,
    rsa: bool = False,
    config_path: Path | None = None,
) -> None:
    """Stop renewing one certificate and optionally purge its local files."""
    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if len(domain) > 253 or not re.fullmatch(
        rf"(?:\*\.)?{label}(?:\.{label})*", domain
    ):
        raise RemovalError(
            "Use a lowercase ASCII domain name, optionally prefixed by '*.'"
        )
    if ecc and rsa:
        raise RemovalError("Choose only one of --ecc and --rsa")

    acme = config["acme_script"]
    certificates = [_discover(acme, domain, ecc=kind) for kind in (False, True)]
    candidates = [
        cert
        for cert in certificates
        if cert.exists and (not (ecc or rsa) or cert.ecc == ecc)
    ]
    if not candidates:
        raise RemovalError(f"No local certificate record found for {domain}")
    if len(candidates) != 1:
        raise RemovalError(
            f"Both RSA and ECC records exist for {domain}; use --rsa or --ecc"
        )
    cert = candidates[0]

    installed_dir = None
    protected = []
    if purge:
        if any(other != cert and other.conf.is_file() for other in certificates):
            raise RemovalError(
                "Another certificate type is still renewing for this domain; "
                "remove it before purging the shared installed files"
            )
        if not isinstance(config.get("ssl_path"), str) or not config["ssl_path"]:
            raise RemovalError("A nonempty ssl_path is required for --purge")
        installed_dir = Path(config["ssl_path"]).expanduser().absolute() / domain
        for path in (Path(acme), config_path or Path("config.jsonc")):
            # Protect both a symlink's directory entry and its resolved target.
            protected.extend((path.absolute(), path.resolve()))
        _check_purge_paths(cert, installed_dir, protected)

    kind = "ECC" if cert.ecc else "RSA"
    print(f"Certificate: {domain} ({kind})")
    print(f"Certificate directory: {cert.conf.parent}")
    if dry_run:
        action = (
            "Would stop renewal" if cert.conf.is_file() else "Renewal already stopped"
        )
        print(f"{action}: {domain}")
        if installed_dir is not None:
            for name in ("private.pem", "fullchain.pem"):
                print(f"Would delete if present: {installed_dir / name}")
            print(f"Would remove directory if empty: {installed_dir}")
            print(f"Would delete certificate directory: {cert.conf.parent}")
        print("Dry run: no removal or file cleanup performed.")
        return

    if cert.conf.is_file():
        result = subprocess.run(
            [acme, "--remove", "-d", domain, *cert.flags], check=False
        )
        if result.returncode:
            raise RemovalError(
                f"acme.sh --remove failed for {domain} (exit {result.returncode}); "
                "no files purged"
            )
        _check_certificate(cert)
        if cert.conf.exists() or not cert.removed_conf.is_file():
            raise RemovalError("acme.sh did not confirm removal; no files purged")
        print(f"Stopped renewal: {domain}")
    else:
        print(f"Renewal already stopped: {domain}")

    if installed_dir is not None:
        try:
            for other in certificates:
                _check_certificate(other)
            if cert.conf.exists() or not cert.removed_conf.is_file():
                raise RemovalError("Certificate removal state changed; no files purged")
            if any(other != cert and other.conf.is_file() for other in certificates):
                raise RemovalError(
                    "Another certificate type is now active; no files purged"
                )
            _check_purge_paths(cert, installed_dir, protected)
            _purge(cert, installed_dir)
        except OSError as error:
            raise RemovalError(
                f"Renewal is stopped, but file cleanup failed: {error}"
            ) from error
    print("config.jsonc is unchanged; apply can request this domain again.")
