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

配置位于仓库根目录的 `.pre-commit-config.yaml`，检查范围限定为 `acme-cloudflare`。
检查依次执行 Ruff lint（含导入排序和自动修复）、Ruff 格式化及 pytest。
pytest 在 Python 文件、`pyproject.toml` 或 `uv.lock` 变更时运行。
各检查通过 `uv run --locked --project acme-cloudflare` 使用项目锁定的开发依赖。
自动修复修改文件后，需要重新暂存修改并再次提交。

## 依赖

- [acme.sh](https://github.com/acmesh-official/acme.sh)
- openssl
- curl
