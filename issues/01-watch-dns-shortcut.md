# watch 在门户已判「不在线」后仍因 DNS 通顺而不登录

- 级别：S4 · 成本：半天 · 标签：`bug` `P0`
- 落点：`src/campus_auth/keepalive.py:44-45`；测试 `tests/test_keepalive.py:31,60,79`
- 决策（Q1）：**门户为准**。DNS 不再参与放行判定，只做归因；另加「连续 3 轮被拒 + DNS 通」的兜底

## 现象

`one_cycle()` 先用 `portal.mine()` 拿到「不在线」，随后：

```python
if net.resolves(probe_host):
    return Cycle(online=False, attempted=False, ok=True, message="DNS 正常，无需登录")
```

直接 `return`，一次登录都不发。

校园门户**劫持 DNS**：认证前 `getaddrinfo("www.baidu.com")` 照样成功。所以这段快速路径在唯一的目标环境里恒为真。

要注意 `mine()` 命中时函数早就提前返回了，所以 DNS 检查**只在门户说「不在线」时执行** —— 它唯一的产出就是省掉那一次本该发的登录。

## 复现（本机已复现）

```bash
python tools/fake_portal.py --port 8801
python -m campus_auth watch --once --url http://127.0.0.1:8801 --ip 10.9.9.9 -a 20240001 -p pw
# 输出：[20:34:19] #1 DNS 正常，无需登录（0.2s）   exit 0
# 门户里没有任何会话，watch 却报健康
```

## 为什么没被测试抓住

三处 keepalive 测试都把 `resolves` patch 成 `False`，等于把「永远不该走这条分支」写成了前提。

## 期望

1. `mine()` 为 None 时直接 `login()`，不再看 DNS。
2. 登录被拒时才查 DNS，结果只用于文案：「（DNS 正常，可能已在线或会话接口异常）」。
3. 兜底：连续 3 轮「被拒 + DNS 通」后，把该轮按健康处理（`ok=True`、`degraded=True`、间隔回到正常值），避免门户会话接口坏掉时把「用户已在线」误当成故障一路退避到 8×interval。
4. 登录成功或 DNS 变为不通时，连续计数清零。

## 影响面

- 会话自然过期（凌晨、跨楼、DHCP 续租）后，watch 长跑空转，日志一路绿灯，用户以为在保活。
- 首轮安装即失效：装完自启，从未登录过一次。

## 失败断言（先红后绿）

- `mine()→None` + `resolves→True` + 登录成功：`login()` 被调用一次，`message` 含「已重新登录」。
- 连续 3 轮被拒且 DNS 恒通：第 3 轮 `ok=True`、`degraded=True`、`message` 含「连续」。
- 被拒且 DNS 不通：`ok=False`，不进兜底。
- 兜底后登录成功：计数清零，`degraded` 不再出现。

## 验收

- 四条断言先红后绿。
- `test_keepalive.py` 三处 `resolves` patch 改为 `True` 后仍全绿（证明不再依赖它）。
- 人工：假门户空状态下 `watch --once` 能建出会话。

## 边界

- 代价是离线时每轮多一次 login；正常退避仍生效（`failures` → `delay * 2**min(failures,4)`），兜底命中后回到正常间隔，稳态 ≤1 次登录/interval。
- `--once` 时计数从 0 起，不会一轮就触发兜底。
- 不引入 ping/HTTP 其他探活方式。
