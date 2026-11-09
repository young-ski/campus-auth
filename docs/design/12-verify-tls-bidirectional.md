# `--verify-tls` 只能开不能关，配置里为 true 时没有逃生口

- 级别：S2 · 成本：半小时 · 标签：`dx` `tls` `good first issue`
- 落点：`src/campus_auth/commands/_common.py:74-75`、`src/campus_auth/cli.py:71`（`tuning` 父参数）

## 现象

```python
if getattr(args, "verify_tls", False):
    overrides["verify_tls"] = True
```

单向赋值。配置文件里写了 `verify_tls = true` 之后，命令行无法覆盖回 false；只能改文件（而自启进程恰恰读文件，于是改文件也会连带影响自启）。

实际场景：某门户的证书过期三天，用户开了校验，然后被卡住。

## 期望

`--verify-tls/--no-verify-tls` 双向（`argparse.BooleanOptionalAction`，3.11 起可用，项目最低版本就是 3.11）；不传时保持「不覆盖」，即 `None`。

## 失败断言

- 配置 `verify_tls = true` + `--no-verify-tls` → 生效值为 false。
- 配置 `verify_tls = true` + 不传 → 仍为 true（不被默认值冲掉）。
- `--verify-tls` 在配置为 false 时置 true（现状不许退化）。

## 验收

- 三条断言先红后绿；`tests/test_cli.py` 增加双向用例。
- `probe --verify-tls --no-verify-tls` 的 help 文本一并更新。

## 边界

- 默认仍为关（校园门户自签是常态，README 的既有论证成立）。
- 只动 flag 定义与 `_config`，不动 `ssl_context`。
