# 本校门户上 probe 判成「锐捷 / 没认出来」

- 级别：S4 · 成本：半天 · 标签：`bug` `probe` `P0` · 已实现（1.7.3）
- 落点：`src/campus_auth/probe.py:37`（JS 属性正则）、`PROBE_PATHS`、`scan.py:_target`

## 现象（2026-11-09，本校网络 10.152.59.163 / UCLINK 实测）

```
$ campus-auth probe
没从劫持页找到门户地址   exit 2
$ campus-auth probe --url https://netauth.huuc.edu.cn:802
判定: 是锐捷 ePortal（本项目暂不支持）   exit 1
$ campus-auth probe --url http://10.210.213.208:802   （README 与 huuc 注释都在用）
HTTP 400 → 判定: 没认出来（5 分）   exit 1
```

给本校学生看的第一条命令，告诉他「换个工具」；而 `login` 是通的。

## 根因（逐层验过）

1. 首页是 Vue SPA，脚本标签写成 `<script src=/eportal/public/static/js/app.3886f7f2.js>`
   —— **属性值没有引号**，只认引号的 `_JS_SRC` 一个都匹配不到，JS 从不被抓。
2. 硬编码的 `/eportal/portal/js/a41.js` 现在只回 `404 eportal action a41.js not found`，
   而且门户对这种不存在的 action 也回 200，只看状态码会把它当样本。
3. SPA 的 JS 里没有 `enc_pwd` / `getkey` / `dr1003`，只有 `wlan_user_ip` 和 `drcom` 字样：
   就算抓到 JS，也够不到「必须命中独有特征」的门槛。
4. 真正的独有证据在匿名会话接口上：`{"result":1,"list":[{"online_session":...,"online_time":...}]}`。
   已在线是多数人首试状态，旧逻辑却把它当异常。
5. 门户 IP 已改成只收 HTTPS，`http://` 一律 400；文档与 `--url` 引导都没跟上。

## 期望（已实现）

- `_JS_SRC` 三种写法都认（`"`、`'`、无引号）。
- 首页不挂 JS 时补两条固定候选，命中 `404 eportal action` 桩就跳过。
- `online_session` / `online_time` 计为独有证据（+30），`DISTINCTIVE` 收进去。
- 会话接口出现该字段时结论里点明「已在线」，不再引导去抓包。
- 劫持页发现失败时退回适配层地址；只有连适配层地址都拿不到才报 2。
- 全部样本都是 400 且是 http 时自动换 https 再探一遍，`target` 报实际用的地址。
- `probe --no-discover` 顺带修好：它以前把 `--adapter` 整个丢掉。

## 失败断言（先红后绿，6 条）

无引号 `src` 能被跟随；固定候选会兜底且跳过 404 桩；`online_session` 能单独判成 drcom；
在线态写进 notes；http 门户会自动重试 https 且 `target` 变成 https；发现失败时退回适配层地址。

## 验收

- 6 条断言先红后绿；真实门户上不给 `--url`、给 http、给 https 三种都 exit 0 且判 drcom。
- 393 个测试与 `ruff check` / `ruff format --check` 全绿。

## 边界

- 跟随跳转仍然不限同源（真实门户常从网关跳到域名，限同源会坏），已知 SSRF 面记在待办里。
- 固定候选只两条，且命中即停，不会把探针变成扫描器。
- 「已在线」没有新增 verdict 值，仍是 `drcom`；`--json` 只增字段，不升 schema。
