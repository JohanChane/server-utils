# acme-cf

ACME SSL 证书管理工具，基于 acme.sh + Cloudflare DNS。

## 安装

```bash
uv sync
```

## 配置

编辑 `config.jsonc`，填入 Cloudflare 凭证和域名列表。

顶层 `reload_cmd` 配置默认重载命令。`domains` 支持域名字符串，也支持使用 `domain` 和 `reload_cmd` 的对象，两种格式可以混用：

```jsonc
{
  "reload_cmd": "sudo systemctl reload nginx",
  "domains": [
    "www.example.com",
    {
      "domain": "api.example.com",
      "reload_cmd": "sudo systemctl reload caddy"
    },
    {
      "domain": "static.example.com"
    }
  ]
}
```

上例中，`www.example.com` 和 `static.example.com` 使用默认命令，`api.example.com` 使用自己的命令。
域名未配置 `reload_cmd` 时继承顶层默认值；显式设置为 `""` 时不执行重载。顶层也未配置时，默认不执行重载。
`install` 会将各域名最终使用的命令传给 acme.sh 的 `--reloadcmd`。

## 使用

```bash
uv run acme-cf apply [--force]   # 签发证书
uv run acme-cf install            # 安装证书到 nginx
uv run acme-cf check              # 检查证书过期时间
uv run acme-cf refresh            # 清除 Cloudflare 缓存
uv run acme-cf list               # 列出 acme.sh 已签发证书

uv run acme-cf -c /path/to/config.jsonc apply
```

## 停止续期与清理证书

```bash
uv run acme-cf remove example.com --purge --dry-run  # 预览停止续期和清理范围
uv run acme-cf remove example.com                    # 仅停止自动续期
uv run acme-cf remove example.com --purge            # 停止续期并清理本地证书
uv run acme-cf remove example.com --ecc              # 明确选择 ECC 证书
uv run acme-cf remove example.com --rsa              # 明确选择 RSA 证书
```

每次必须明确指定一个域名。程序通过 `acme.sh --info` 获取实际证书目录，自动识别 RSA 或 ECC 证书；两种证书记录同时存在时，需要使用 `--ecc` 或 `--rsa` 明确选择，两者不能同时使用。
`remove` 调用 `acme.sh --remove` 停止自动续期，保留本地证书文件。
`--purge` 额外删除 acme.sh 中对应的证书目录，以及 `<ssl_path>/<domain>/private.pem` 和 `fullchain.pem`；安装目录为空时才删除该目录，其他文件保留。
同一域名的另一种证书仍在续期时，`--purge` 会拒绝清理，避免删除另一张证书可能仍在使用的部署文件；另一种证书已停止续期时不阻止清理。
已经停止续期的证书可以再次使用 `--purge` 清理。停止续期或文件清理失败时，命令以非零状态退出；`--dry-run` 只查询并显示计划，不执行停止续期或文件删除。

删除安装证书前，请先解除 Nginx/Caddy 配置对这些文件的引用，否则后续重载可能失败。
删除命令不吊销证书、不删除 Cloudflare DNS，也不执行 `reload_cmd`。
`config.jsonc` 保持不变，域名仍保留在 `domains` 中；后续运行 `apply` 会再次尝试申请证书。

## 测试

```bash
uv run pytest tests -v
```

`uv run` 会自动安装开发依赖，并使用项目虚拟环境中的 pytest 运行测试。

## 提交前检查

在 `acme-cloudflare` 目录运行：

```bash
uv run pre-commit install          # 安装 Git hook，每个本地仓库执行一次
uv run pre-commit run --all-files  # 检查全部已跟踪文件
uv run pre-commit                  # 检查暂存文件
```

配置位于仓库根目录的 `.pre-commit-config.yaml`，按项目分别检查 `acme-cloudflare` 和 `sub-mgr`。
检查依次执行 Ruff lint（含导入排序和自动修复）、Ruff 格式化及 pytest。
pytest 在 Python 文件、`pyproject.toml` 或 `uv.lock` 变更时运行。
各检查通过 `uv run --locked --project acme-cloudflare` 使用项目锁定的开发依赖。
自动修复修改文件后，需要重新暂存修改并再次提交。

## 依赖

- [acme.sh](https://github.com/acmesh-official/acme.sh)
- openssl
- curl
