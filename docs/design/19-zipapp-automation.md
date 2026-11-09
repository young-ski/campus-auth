# pyz 靠手传，还夹着 31 个 .pyc 和整个 egg-info

- 级别：S2 · 成本：1 天 · 标签：`ci` `release` · 状态：已实现
- 落点：`.github/workflows/publish.yml`、新增 `tools/build_zipapp.py`、`.gitattributes`

## 现象

`dist/` 被 gitignore，`campus-auth.pyz` 由维护者本地 `python -m zipapp src` 打完手传到 Release，
`publish.yml` 里没有任何一步构建它。后果：

- 忘传就少一个安装通道（README 明确推荐它给没有 pip 的机器）；
- `python -m zipapp src` 直接压 `src/`，把 `__pycache__`（31 个 `.cpython-314.pyc`）和
  `campus_auth.egg-info/` 一起塞进去，402 KB 里相当部分是残留；
- `.gitattributes` 没有 `*.pyz binary`，diff 里会被当文本；
- 没有校验和，下载方无法先核对。

## 复现

```bash
python -m zipapp src -m campus_auth.cli:main -o /tmp/x.pyz
python -c "import zipfile;n=zipfile.ZipFile('/tmp/x.pyz').namelist();print(len(n), sum('__pycache__' in x or '.egg-info' in x for x in n))"
```

## 期望

- 新增 `tools/build_zipapp.py`：只用干净副本打包，产出 pyz + `SHA256SUMS`。
- `publish.yml` 在 build 作业里调它，产物作为 Release 附件，需要 `contents: write`。
- CI 冒烟复用同一个脚本，发布与 CI 不再各走一套。
- `.gitattributes` 标记 `*.pyz binary`。

## 失败断言

- 构建出的 pyz 里没有 `__pycache__` / `.pyc` / `.egg-info`。
- pyz 能跑：`python out.pyz adapters` 退 0。
- `publish.yml` 含 `build_zipapp` 与 `SHA256SUMS`；含 `gh release create` 与 `contents: write`。
- `.gitattributes` 含 `*.pyz binary`。

## 验收

- 四条断言先红后绿；`dist/campus-auth.pyz` 由 402 KB 降到 53 KB、条目 71 → 30。

## 边界

- 不做可复现构建（zipapp 的 mtime 未归一），校验和只保证「下载的内容没被改」。
- 不把 pyz 提交进仓库，仍走 Release 附件。
