# 配置里的数值写法与越界端口都掉成 exit 70 traceback

- 级别：S3 · 成本：半天 · 标签：`bug` `config` `good first issue`
- 落点：`src/campus_auth/config.py:119`（字符串字段无 `str()` 兜底）、`src/campus_auth/runner.py:45`（`parts.port`）、`src/campus_auth/cli.py:245`（兜底 except）

## 现象 A：TOML 里账号不加引号

```toml
account = 81456789
```

`_coerce()` 只处理 `timeout/interval/jitter/retries/verify_tls`，其余走 `return value`，于是 `account` 是 `int`。下游第一处 `ord(ch)`（`crypto.py:31`）就崩；即使绕过，`base.py:254` 的 `account in actual` 还会再崩一次。

本机复现：

```bash
printf 'adapter = "huuc"\naccount = 81456789\npassword = "pw"\n' > /tmp/num.toml
python -m campus_auth urls --config /tmp/num.toml -i 10.1.2.3 -o /tmp/u2
# TypeError, exit 70 + traceback
```

## 现象 B：端口越界

`http://h:99999` 时 `urlsplit(...).port` 抛原生 `ValueError`，`_host_port` 不接，`cli.main` 也没有 `ValueError` 分支 → 同样 exit 70 traceback。

同一类错误的正确形态是 `exit 2` + 一句人话（README 的退出码表：2 = 配置问题）。

## 期望

- 字符串类字段（`adapter/account/password/operator/mac/ip/base_url/probe_host`）统一 `str()` 归一；`bool`/`None` 除外。
- 端口越界归为 `ConfigError`：「`base_url` 的端口非法: 99999」。
- 极端兜底：`cli.main` 把 `ValueError` 也纳入配置错误，别让它落进 traceback。

## 失败断言

- `account = 81456789` 的配置能跑通 `init`/`urls`，且拼出的账号是 `81456789`。
- `--url http://h:99999` → exit 2，stderr 含「端口」。
- `--url nonsense` → exit 2（现为 3，另见 #16）。

## 验收

- 三条断言先红后绿。
- `pytest` 全绿；`tests/test_config.py` 增加数字化字段用例。

## 边界

- 不引入 pydantic 之类依赖，仍是手写 `_coerce`。
- `verify_tls = "yes"` 等既有宽松解析保持不变。
