# 两个 `watch --log` 写同一文件会互相写崩

- 级别：S3 · 成本：半天 · 标签：`bug` `logfile` `concurrency`
- 落点：`src/campus_auth/logfile.py:29-53`（`write` / `_rotate`），触发点 `:40` `newer.replace(older)`

## 现象

没有任何锁或 pid 文件。轮转时对同一路径 `replace`，而另一个进程正开着那文件：

- Windows 上 `PermissionError` / WinError 32；
- 异常从 `write()` 直接冒出（`print` 链路），`watch` 收摊，exit 70 + traceback。

这在 `install` 装了自启、用户又手工跑一次 `watch` 时必然发生（双开是常见误操作）。

## 复现

两个进程同时跑，或同进程内两个 `RotatingLog(同一路径, limit=1024)` 交替写超限：

```
FileNotFoundError / PermissionError: [WinError 32] ... 另一个程序正在使用此文件
```

## 期望

轮转是「尽力而为」，不许让观测设施打死主循环：

- `write()` 内 `try/except OSError`，失败则关闭句柄、延迟到下次重开，本轮文本不丢（退化为追加）。
- `_rotate()` 失败时保留原句柄，不要置 `None` 后依赖 `_open` 成功。
- 可选：`O_EXCL` 建 `watch.log.pid` 做单实例提示，但**不作为前置强制**（多实例仍应能用）。

## 失败断言

- 句柄被另一实例占用时，`write()` 不抛异常，文本仍进文件。
- `replace` 抛 `PermissionError` 后，下一次 `write` 仍能写入。
- 单实例正常轮转的既有用例（`tests/test_logfile.py`）不变。

## 验收

- 断言先红后绿（可 monkeypatch `Path.replace` 抛 `PermissionError` 构造）。
- 手工：开两个 `watch --log x.log --interval 5`，各跑 3 轮，两边都不倒。

## 边界

- 不做跨进程锁文件（会引入清理与残留问题），目标只是「不崩、不丢本轮日志」。
- 与 #2 同属日志面，但互不依赖。
