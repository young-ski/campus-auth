# local_mac 按子串匹配 IP，会返回别的网卡的 MAC

- 级别：S3 · 成本：半天 · 标签：`bug` `net` `windows` `good first issue`
- 落点：`src/campus_auth/net.py:58`

## 现象

```python
for block in re.split(r"\r?\n\s*\r?\n", text):
    if ip and ip not in block:
        continue
```

用子串判「是不是这块网卡」。查 `10.138.14.2` 时，先出现的 `10.138.14.27` 那个块包含子串 `10.138.14.2`，于是命中错误的块、返回那块的 MAC。

本机复现（替换 `_run` 后）：

```
local_mac('10.138.14.2') = AABBCCDDEEFF   # 期望 112233445566
```

## 影响面

- MAC 绑定 / MAC 认证的门户会直接用错 MAC，表现为「密码对但认证失败」。
- `unbind` 会拿错 MAC 去解绑，可能解掉另一台设备。
- 新版 Dr.COM 门户多数不强校验 MAC，所以问题长期潜伏；一旦适配层打开校验就成硬故障。

## 期望

按「该块的 IPv4 行」精确匹配，而不是整块子串：

- 优先 `re.search(rf"IPv4[^:：]*[:：]\s*{re.escape(ip)}\b", block)`（中英文冒号都认）。
- 取不到再退回现有子串逻辑，避免英文以外的 `ipconfig` 变体直接失效。

## 失败断言

- 构造两块相邻网卡的 `ipconfig /all` 文本，同前缀 IP 必须各自取到自己的 MAC。
- IP 不存在时返回 `None`。
- `ip=None` 时行为不变（取第一个可解析块）。

## 验收

- 断言先红后绿；新增 `tests/test_net.py`（目前 net 层无单测）。
- 真机：本机 `campus-auth status` 打印的 MAC 与 `ipconfig /all` 里出口网卡一致。

## 边界

- 只动 Windows 分支；Linux 走 `ip route` + sysfs，已按接口名取，不受影响。
- `local_mac` 失败本就不致命（全 0 服务端也接受），所以退回逻辑要保留。
