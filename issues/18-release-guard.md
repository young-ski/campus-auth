# 发布链全靠人手滑：版本可漂、tag 可绕、pyz 手传

- 级别：S2 · 成本：1 天 · 标签：`ci` `release` · 状态：已实现
- 落点：`.github/workflows/publish.yml`、`src/campus_auth/__init__.py`、新增 `tools/check_version.py`

## 现象

1. 版本守卫被 `if: startsWith(github.ref, 'refs/tags/v')` 包着，`workflow_dispatch` 时
   整段跳过 —— 手工触发的发布可以带任意版本上传。
2. 守卫只比 tag 与 `pyproject.toml`；`--version` 读的 `__init__.__version__` 从不参与比较，
   两处能悄悄分家。
3. 从打 tag 到上传之间一次测试都不跑：tag 打在红提交上照样发版。

## 复现

```bash
python -c "import re;print(re.search(r'__version__ = \"([^\"]+)', open('src/campus_auth/__init__.py').read()).group(1))"
grep -n "startsWith" .github/workflows/publish.yml
grep -n "pytest" .github/workflows/publish.yml   # 空
```

## 期望

- 版本一致性做成脚本（`tools/check_version.py`），同时比 `pyproject` 与 `__init__`，带 tag 时再比 tag。
- 守卫去掉 `if:`：dispatch 传空串，退化成只比两处源码。
- 上传前跑 `pytest`。

## 失败断言

- `pyproject` 与 `__init__` 不一致 → 脚本退 1。
- tag 与版本不一致 → 退 1 并打印两边的值。
- `publish.yml` 里 `pytest` 出现在 `pypi-publish` 之前。
- 守卫那段不再出现 `if: startsWith`。

## 验收

- 四条断言先红后绿。
- 故意把 `__init__` 写错一位，`pytest` 变红。
- `workflow_dispatch` 一次，build 作业在不一致的版本上失败。

## 边界

- 不改 `environment: pypi` 与 OIDC 可信发布。
- 版本号仍由人改，脚本不代改。
