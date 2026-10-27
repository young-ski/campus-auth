# Windows 自启装出来即崩：pythonw 下 `sys.stdout is None`，`Tee.write` 不判空

- 级别：S4 · 成本：半天 · 标签：`bug` `P0` `windows`
- 落点：`src/campus_auth/logfile.py:74-76`、`src/campus_auth/install.py:141-142`、`src/campus_auth/commands/watch.py:33`

## 现象

`install` 在 Windows 上会主动把解释器换成 `pythonw.exe`（`install.py:141-142`，为的是登录时不弹黑窗）。detached 的 pythonw 进程里 `sys.stdout is None`。

而 `watch --log` 会构造 `Tee(sys.stdout, log)`（`watch.py:33`），`Tee.write` 直接 `stream.write(text)`（`logfile.py:74-76`），遇到 `None` 抛 `AttributeError`。

`install.py:82-84` 生成的 `_watch_command` **永远带 `--log`**，所以出货路径 100% 命中。`.cmd` 于是每 31 秒把它重新撞死一次（`install.py:148-151`）。

## 复现（本机已复现前半段）

```bash
python -c "
import sys
from pathlib import Path
from campus_auth.logfile import Tee, RotatingLog
Tee(None, RotatingLog(Path('/tmp/t.log'))).write('x')
"
# AttributeError: 'NoneType' object has no attribute 'write'
```

完整复现（Windows）：`install` 之后手工跑到 detached，观察 rc=120、无输出、`watch.log` 不生成。

注意对照：`_force_utf8()` 已经能容忍 `None`（`cli.py:213-215` 用 `contextlib.suppress(AttributeError, ...)`），说明这个坑此前被局部绕过，只是没覆盖 `Tee`。

## 期望

- `Tee.__init__` 丢掉 `None` 流。
- `sys.stdout is None` 时把日志流直接当 stdout（输出不丢，进日志）。
- 极端情况下一个流都不剩也不能崩，`write` 静默降级。

## 影响面

- Windows 是 README 与 install 的主线平台；自启是「长期用」的唯一入口。
- 失败形态极隐蔽：任务管理器「启动」里看得见条目，机器上却什么都没发生，日志文件甚至没被创建。

## 失败断言

- `Tee(None, sink).write("x")` 不抛异常，且 `sink` 收到 `x`。
- `Tee(None, None).write("x")` / `.flush()` / `.isatty()` 均可用。
- `tools/check_install_artifacts.py` 增一条 `Tee(None, …)` 断言（该脚本 CI 会跑）。

## 验收

- 上述断言先红后绿。
- 真机（或 CI 的 windows-latest）以 `DETACHED_PROCESS` 跑一次 `pythonw -u -m campus_auth watch … --log x.log --once`，rc=0 且 `x.log` 有内容。
- `install --dry-run` 产物不变。

## 边界

- 只动输出装配，不动轮转策略；`RotatingLog` 的并发问题另见 #10。
