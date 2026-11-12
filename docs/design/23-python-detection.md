# 装了 Python 3.12，安装脚本却说找不到

- 级别：S2 · 成本：半天 · 标签：`installer` `windows` `P1` · 已实现（1.7.5）
- 落点：`packaging/install.cmd` 的 `:find_py`、`:scan_registry`、`:scan_dirs`；`pyproject.toml`

## 现象（同学实测，2026-11-12）

Windows 11 25H2（26200），命令行里 `python` 显示 `3.12.14`，双击 `install.cmd` 后仍提示
「没找到 Python 3.11 或更新版本」，随后打开 python.org。另一位同学是 3.10.12，卡在版本门槛。

## 根因

旧脚本的探测只有两条路：

```bat
where py            & py -3 -c "...(3,11)..."
where python        & python -c "...(3,11)..."
```

两条都不成立时直接判死。现实中至少有四种「装了但探不到」：

1. **解释器由 uv 装的**（3.12.14 正是 uv 的构建号）。uv 把它放在
   `%APPDATA%\uv\python\cpython-3.12.14-windows-x86_64-none\`，**不写注册表**、不在
   `Programs\Python` 下；py 启动器虽然 `py -0p` 能列出它（`-V:Astral/CPython3.12.14`），
   但 `py -3.12` 选不中——本机实测就是 `No suitable Python runtime found`。
2. **PATH 只在某个 shell 里生效**：从资源管理器双击继承的是系统/用户 PATH。
3. **python.org 装在默认目录但没勾 Add to PATH**。
4. 3.10 被版本门槛挡掉（不是探测问题，是需求本身不合理）。

另外 `py <version>` 在没装该版本时可能去开 Microsoft Store，这在同学的机器上是二次惊吓。

## 决定

- 探测顺序：显式参数 → `py -3.13`…`-3.10`/`py -3` → PATH 上的 `python`/`python3` →
  注册表 `PythonCore\*\ExecutablePath`（HKCU + HKLM）→ 默认目录（python.org 用户级/系统级、
  uv、conda、miniforge、scoop、`~/.local/bin`）。设 `PYLAUNCHER_ALLOW_INSTALL=0`，不让启动器弹商店。
- 找不到时**打印现场**：`where python`、`where py`、`python -V`、`py -0p`，包在
  `---- cut here ----` 之间，让同学直接整段粘回来。
- 允许显式指定：`install.cmd "C:\...\python.exe"`。
- **版本门槛降到 3.10**：代码里唯一的 3.11 依赖是 `tomllib`；内置 `tomli`（MIT，保留上游
  LICENSE）给 3.10 用，`requires-python` 改 `>=3.10`，CI 矩阵补 3.10。

## 失败断言（先红后绿）

`.cmd` 必须同时出现：注册表查询、`py -3.12`、`Programs\Python`、`uv\python`、`anaconda3`、
`scoop`、`MINPY=3.10`、`PYLAUNCHER_ALLOW_INSTALL=0`、可粘贴的现场块、显式参数入口；
`tomllib` 不可用时 `campus_auth.config` 必须退到内置解析器且解析结果一致。

## 验收

- 本机实测：默认路径 `Python: py -3`；显式参数 `Python: "D:\Program Files\Python314\python.exe"`；
  注册表兜底能取到 `D:\Program Files\Python314\python.exe`；uv 目录被扫到。
- 包里 pyz 含 `campus_auth/_vendor/tomli/`，3.10 路径由 CI 的 3.10 作业覆盖。
- 436 测试与 ruff 全绿。

## 边界

- 不自动安装 Python：认证前下载不动，静默装一个运行时比报错更难排查。
- 仍可能漏掉自定义目录；此时 `install.cmd "<路径>"` 是兜底，不是失败。
- `src/` 与 `tests/` 用 `ast.parse(feature_version=(3, 10))` 校验过，无 3.11 语法。
