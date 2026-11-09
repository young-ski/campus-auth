# 重试面太窄：500/502 不重试，`retry-after` 小写还被丢掉

- 级别：S1 · 成本：半天 · 标签：`bug` `transport` `good first issue`
- 落点：`src/campus_auth/portal.py:191`（重试状态码）、`src/campus_auth/transport.py:84,88`（`dict(headers)` 丢大小写无关性）

## 现象 A：只重试 429/503

```python
if response.status in (429, 503) and attempt < self.retries:
```

前置代理偶发一次 500/502 就整次登录失败。已有的指数退避 + 抖动与 `Retry-After` 解析都是好料子，只是被过窄的白名单挡住了。

本机复现（`FakeTransport((500,…), (200,…))`）：只请求 1 次即 `TransportError`。

## 现象 B：头名大小写敏感

`transport.py:84,88` 用 `dict(response.headers.items())` 把 `email.message.Message` 展平成普通 dict，丢掉了它的大小写无关语义；随后 `portal.py:192` 用 `headers.get("Retry-After")` 精确查。

代理发小写 `retry-after: 20` 时取不到 → 走 fallback：

```bash
python -c "
from campus_auth.transport import Response
print(Response(429,'x',{'retry-after':'20'}).headers.get('Retry-After'))  # None
"
```

实测退避 2.0 s 而不是 20 s。

## 期望

- 重试状态码扩到 `{429, 500, 502, 503, 504}`（仍不进 4xx）。
- 头键统一 `lower()` 化，取值也 `lower()`；或保留 `Message` 原对象。
- 两处都不改 0.5–60 s 的夹取与抖动。

## 失败断言

- 500、502 各一次后成功 → 请求 2 次并返回结果。
- 400 不重试。
- 小写 `retry-after: 20` → 退避 ≈20 s（用假 sleep 断言）。
- `retry-after` 为 HTTP 日期时行为不变。

## 验收

- 四条断言先红后绿；`tests/test_portal.py` 已有重试用例可扩。
- `pytest` 全绿，注意现有用例断言的是 3 次请求次数，改动后逐条核对。

## 边界

- `ParseError` 仍不重试（重发还是一样）。
- 4xx 一律不重试，包括 408/425（保持现状，别扩大）。
