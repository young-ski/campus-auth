# `--json` 输出格式（schema 1）

给脚本和监控用。`--json` 时 **stdout 只有一个 JSON 对象**（`watch` 是每行一个事件对象），
面向人的文案一律进 **stderr**。

支持这件事的只有这九个命令：`probe`、`status`、`whoami`、`onlinelist`、`login`、`logout`、`unbind`、`check`、`watch`。
其余命令（`init`、`adapters`、`urls`、`password`、`install`、`uninstall`）**不接受** `--json`，
argparse 会直接报「unrecognized arguments」并以 2 退出，不会静默吐人话。

**稳定性承诺**

- 每个对象都带 `"schema": 1`。同一个 schema 版本内**只增字段、不改语义、不删字段**。
- 消费方必须忽略不认识的字段；别把整个对象 `==` 比较。
- 真要破坏性改动时 `schema` 加一，并在 `CHANGELOG.md` 标出来，提前一个版本说明。
- 机器可读版本在 [`json.schema.json`](json.schema.json)，CI 会拿真实输出对一遍。

**通用约定**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema` | 整数 | 上面那个版本号，恒为 `1` |
| `ok` | 布尔 | 命令是否成功；失败时用下面「错误形态」的对象 |

退出码仍按 README 的表：成功 0、被拒/未在线 1、配置 2、环境 3、传输 4。
**判断成败请看 `ok` / 退出码，不要解析 `msg`。**
人读文案在 stderr：`2>/dev/null` 会看不到提示，但 stdout 始终可解析。

---

## `probe --json`

判门户类型。只读，不需要密码。

```json
{
  "schema": 1,
  "ok": true,
  "target": "https://10.210.213.208:802",
  "verdict": "drcom",
  "is_drcom": true,
  "confidence": "高",
  "score": 155,
  "evidence": [
    { "name": "JS 里有 enc_pwd（异或加密函数）", "weight": 30, "hit": true, "detail": "" }
  ],
  "missing": [],
  "notes": []
}
```

一条探针都没通时是错误形态（`ok: false` + `error`），退出码 3（不在校园网）或 4（传输失败）。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `target` | 字符串 | 实际探测的地址：`--url` > 从劫持页发现的 > 适配层默认值 |
| `verdict` | 枚举 | `drcom` / `likely-drcom` / `ruijie` / `srun` / `unknown`。后两者本项目不支持 |
| `is_drcom` | 布尔 | `verdict` 是前两项时为 `true` |
| `confidence` | 枚举 | `高` / `中` / `低`，由分数阈值决定 |
| `score` | 整数 | 最高一家的分数，仅供调参参考 |
| `evidence[]` | 数组 | 每条 `{name, weight, hit, detail}`；`hit: false` 是没中的信号 |
| `missing[]` | 字符串数组 | 判成“证据不全”时列出还缺什么 |
| `notes[]` | 字符串数组 | 人读的补充说明，可能含跟到的跳转 host |

## `status --json`

看会话。

```json
{
  "schema": 1,
  "online": false,
  "any_online": true,
  "ip": "10.138.14.27",
  "account": "081456789",
  "sessions": [{ "online_ip": "10.138.14.27", "user_account": "别人的号", "ours": false }]
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `online` | 布尔 | **你自己的**会话在不在（IP 与账号都对上） |
| `any_online` | 布尔 | 门户里有没有任何会话，含别人的 |
| `ip` | 字符串 | 本机出口 IP |
| `account` | 字符串 | 配置里的账号；没填会先以退出码 2 结束，不输出 JSON |
| `sessions[]` | 数组 | 门户返回的原始行 + `ours: bool`。原始字段由门户决定，不保证稳定 |

## `whoami --json`

这台机器现在挂的是哪个账号。只读会话列表，不需要密码，也不需要先填 `account`。

```json
{
  "schema": 1,
  "ok": true,
  "found": true,
  "ip": "10.138.14.27",
  "mac": "AABBCCDDEEFF",
  "account": "081456789",
  "accounts": ["081456789"],
  "matches_config": true
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ok` | 布尔 | 与 `found` 同值，方便统一用 `jq -e .ok` |
| `found` | 布尔 | 本机 IP（且 MAC 对得上，门户两者都回时才比）上有没有会话 |
| `ip` | 字符串 | 本机出口 IP |
| `mac` | 字符串 | 本机 MAC（12 位十六进制，取不到为空串） |
| `account` | 字符串 | 门户上这条会话的账号；没有会话或门户不回账号时为空串 |
| `accounts` | 字符串数组 | 同一 IP 上的全部账号，通常只有一个 |
| `matches_config` | 布尔 \| null | 与配置里的 `account` 是否一致；没配账号、或门户不回账号时为 `null` |

`found` 为 `false` 时退出码 1，JSON 照常输出（不是错误形态）。

## `onlinelist --json`

扫网段找会话。门户只按单个 IP 回答，这里逐地址问完再汇总；`--range` 决定扫哪儿。

```json
{
  "schema": 1,
  "ok": true,
  "scanned": 254,
  "failed": 1,
  "failed_ips": ["10.152.59.2"],
  "retried": 3,
  "cancelled": false,
  "ranges": ["10.152.59.1", "10.152.59.2"],
  "sessions": [
    {
      "ip": "10.152.59.163",
      "account": "081456789",
      "mac": "AABBCCDDEEFF",
      "online_since": "2026-11-17 17:47:02",
      "seconds": 541,
      "ours": true
    }
  ]
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ok` | 布尔 | 至少有一个地址问成功；全部失败为 `false`（退出码 4） |
| `scanned` | 整数 | 覆盖到的地址数（首次问过的，重试不重复计）；被 Ctrl-C 打断时小于总数 |
| `failed` | 整数 | 重试之后仍然失败的地址数 |
| `failed_ips` | 字符串数组 | 最终失败的地址，方便原样再查一次 |
| `retried` | 整数 | 因失败被重新问过的次数（一轮重试多个地址就计多个） |
| `cancelled` | 布尔 | 是否被 Ctrl-C 打断（此时退出码 130） |
| `ranges` | 字符串数组 | 展开后的地址清单，不是原始 `--range` 写法 |
| `sessions[]` | 数组 | 找到的会话；字段见下 |

`sessions[]` 的字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ip` | 字符串 | 会话的对端 IP |
| `account` | 字符串 | 账号；门户没回时为空串 |
| `mac` | 字符串 | 门户回的 MAC，没有则为空串 |
| `online_since` | 字符串 | 上线时间，门户没回时为 `?` |
| `seconds` | 整数 | 已在线秒数，解析不了时为 0 |
| `ours` | 布尔 | 是不是本机 IP 上的会话 |

`--json` 与 `-e -`（CSV 写 stdout）不能同用；写文件时 CSV 照常生成，JSON 仍在 stdout。

失败地址默认会降并发重试一轮（`--retry 0` 关闭）；`retried` 记重试次数，`failed_ips`
是重试后仍然失败的地址。名单类命令不把“没扫到人”当失败，退出码看 `ok`。

## `login --json`

认证一次。

```json
{
  "schema": 1,
  "ok": true,
  "result": true,
  "msg": "认证成功",
  "ret_code": 0,
  "hint": "",
  "ip": "10.138.14.27"
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ok` | 布尔 | 认证后复查确认在线。**这才是成败** |
| `result` | 布尔 | 服务端是否接受了这次请求 |
| `msg` | 字符串 | 服务端原文 |
| `ret_code` | 整数 \| null | 服务端返回码，门户不给则为 `null` |
| `hint` | 字符串 | 把含糊报错翻译成人话，没有则为空串 |
| `ip` | 字符串 | 本次认证使用的 IP |
| `already_online` | 布尔 | 本轮之前就已经在线，没有真的发认证；此时 `ok` 为 `true` |

## `check --json`

只判定在线，不看会话内容，最适合监控轮询。

```json
{ "schema": 1, "ok": false, "online": false }
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ok` | 布尔 | 与 `online` 同值，方便统一用 `jq -e .ok` |
| `online` | 布尔 | 本机（IP 与账号都对上）是否在线 |

查在线这一步本身失败时是错误形态，错误对象里同样带 `online: false`。

## `logout --json` / `unbind --json`

```json
{ "schema": 1, "ok": true, "msg": "注销成功" }
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ok` | 布尔 | 服务端是否认了这次操作 |
| `msg` | 字符串 \| null | 服务端原文，可能为 `null` |

`unbind` 在解析不出 JSON（门户回 HTML）时输出错误形态：

```json
{ "schema": 1, "ok": false, "error": "响应里没有可解析的 JSON 对象: …" }
```

## `watch --json`

每行一个事件对象，不再有人读文案。先来一条 `start`：

```json
{
  "schema": 1,
  "event": "start",
  "adapter": "huuc",
  "portal": "https://netauth.huuc.edu.cn:802",
  "account": "081456789",
  "operator": "none",
  "ip": "10.138.14.27",
  "interval": 120.0,
  "log": null
}
```

之后每轮一条 `cycle`：

```json
{
  "schema": 1,
  "event": "cycle",
  "t": "14:09:17",
  "cycle": 1,
  "online": true,
  "attempted": false,
  "ok": true,
  "msg": "仍在线",
  "elapsed_ms": 125
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event` | 枚举 | `start` / `cycle` |
| `t` | 字符串 | 本机时间 `HH:MM:SS` |
| `cycle` | 整数 | 第几轮，从 1 开始 |
| `online` | 布尔 | 本轮结束时是否确认在线 |
| `attempted` | 布尔 | 本轮是否真的尝试登录 |
| `ok` | 布尔 | 这一轮健不健康（失败会进退避） |
| `msg` | 字符串 | 本轮结论 |
| `elapsed_ms` | 整数 | 本轮耗时毫秒 |

`watch` 是长跑进程，被信号打断时以退出码 130 结束。

## 错误形态

配置 / 环境 / 传输类错误抛出前若带了 `--json`，输出：

```json
{ "schema": 1, "ok": false, "error": "缺少必填项: account" }
```

错误信息在 stderr 上还会有人读版本，两者内容一致。
