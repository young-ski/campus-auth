# `--mac` 只校验长度，`ZZZZZZZZZZZZ` 也能过

- 级别：S2 · 成本：半小时 · 标签：`bug` `config` `good first issue`
- 落点：`src/campus_auth/runner.py:57-58`

## 现象

```python
if mac and len(mac) != 12:
    raise ConfigError(...)
```

只数长度。`--mac ZZZZZZZZZZZZ` 通过校验，一路拼进 `wlan_user_mac` 发给服务端；错误形态是服务端含糊拒绝，而不是本地报错。

## 期望

`re.fullmatch(r"[0-9A-F]{12}", mac)` 才算合法（`runner.py` 已把 `:`/`-` 去掉并大写了）。

文案保持现状的排障口吻即可：「MAC 看起来不对: 'ZZZZZZZZZZZZ'，应为 12 位十六进制」。

## 失败断言

- `ZZZZZZZZZZZZ` → `ConfigError`（exit 2）。
- `AA:BB:CC:DD:EE:FF`、`aa-bb-cc-dd-ee-ff`、`AABBCCDDEEFF` 三种写法均通过。
- 空 MAC 仍放行（走全 0 兜底）。

## 验收

- 断言先红后绿；`tests/test_cli.py` 补一条 `--mac` 用例。
- 手工：`campus-auth status --mac ZZZZZZZZZZZZ` → exit 2。

## 边界

- 只在有值时校验，`config.mac` 为空不报错。
- 与 #6 相邻但独立：那条管「自动探测取错」，这条管「手填写错」。
