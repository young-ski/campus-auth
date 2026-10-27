# probe 把通用 nginx 登录页判成 Dr.COM

- 级别：S2 · 成本：半天 · 标签：`bug` `probe` `P0`
- 落点：`src/campus_auth/probe.py:117`（nginx 信号）、`:145`（`THRESHOLD["drcom"] = 40`）

## 现象

只要同时命中：

- `wlan_user_ip`（+20，`probe.py:98`）
- `"ret_code"|"result":`（+15，`probe.py:99-105`）
- 「Server 是 nginx 且端口像网关」（+10，`probe.py:117`）

合计 45 ≥ 阈值 40，`MARGIN` 又轻易满足，于是 `verdict=drcom`、退出码 0（「是 Dr.COM」）。

但第三条对**任何** 80/443/8080/8443/802 的 nginx 站点都成立，等于是白送 10 分。判错的代价正是 probe 存在的理由：让人 clone 下来照着 `generic` 配一整天。

## 复现

```bash
python -c "
from campus_auth.probe import analyze
s={'body':'<form action=/login><input name=wlan_user_ip></form> {\"result\":0}'}
a=analyze(s, server='nginx', port=80)
print(a.verdict, a.score)   # drcom 45
"
```

## 期望

「是 Dr.COM」这一档必须有独有特征支撑：命中 `enc_pwd` 或 `getkey`（权重 30/25）才准许决胜；仅靠三条通用信号时降为 `likely-drcom`（exit 1，仍给证据清单与下一步）。

可替代方案：阈值 40 → 55，并给 nginx 信号减到 5 分。二选一，倾向后者更小。

## 失败断言

- 上例必须**不是** `drcom`（是 `likely-drcom` 或 `unknown`）。
- 真样本 `DRCOM_SAMPLES`（`tests/test_probe_against_fakes.py`）仍必须 `drcom` / 高置信度。
- 老门户无 `jsVersion` 的样本（`test_drcom_without_jsversion_is_still_drcom`）不许退化。

## 验收

- 三条断言先红后绿。
- 对 `tools/fake_portal.py` 的 drcom 与 router 两种样式各跑一次 `probe`，结论分别为命中与未命中。

## 边界

- 不新增探针请求，不加网络成本。
- 降低假阳性的同时会略微牺牲老门户的判定强度，用 `missing[]` 与 `likely-drcom` 的文案补偿。
