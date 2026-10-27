# 钥匙串的「成功」是假的：`delete()` 恒真，`available()` 认 fail 后端

- 级别：S2 · 成本：半天 · 标签：`bug` `credentials`
- 落点：`src/campus_auth/credentials.py:61-68`（`delete`）、`:24-32`（`available`）

## 现象 A：删不掉也报成功

```python
with contextlib.suppress(Exception):
    keyring.delete_password(SERVICE, _user(adapter, account))
return True
```

后端锁着、D-Bus 没起、macOS 弹窗被拒 —— 全部吞掉并返回 `True`，`password --forget` 于是打印「已从钥匙串删除」，下次 `login` 却还取到旧密码。

## 现象 B：`available()` 把 fail 后端当可用

```python
return keyring.get_keyring() is not None
```

`keyring.backends.fail.Keyring` 是个永远抛异常的单例，非 `None` 所以判真。于是 `init` 不会提醒「装不上钥匙串，请用环境变量」，用户按提示 `password` 存、其实没存。

## 期望

- `delete()`：区分「本来就没有」与「后端报错」。前者仍返回 `True`（幂等），后者返回 `False` 并由 `--forget` 报错且非 0 退出。
- `available()`：排除 `fail` 后端（判类名/模块名含 `fail`，或实测一次 `get_password`）。
- 两者都不许把异常静默成成功。

## 失败断言

- 后端 `delete_password` 抛 `RuntimeError` → `delete()` 返回 `False`，`password --forget` 退出码非 0 且提示「删不掉」。
- `get_keyring()` 返回 `fail.Keyring()` → `available()` 为 `False`，且 `init` 打印环境变量兜底提示。
- 后端正常但没有该条目 → `delete()` 仍为 `True`（幂等）。

## 验收

- 三条断言先红后绿；`tests/test_credentials.py` 用假 backend 构造。
- `pytest` 全绿（`conftest.py` 全局禁 keyring 的夹具不变）。

## 边界

- 不改 key 命名（`服务/适配层/账号`）。
- 不改 `get()` 的「取不到就当没有」语义 —— 那条是刻意的。
