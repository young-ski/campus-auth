# campus-auth

**Dr.COM / eportal 校园网门户认证客户端。** 一行命令登录，断线自动重连，学校差异全部塞进可插拔的适配层。

> A CLI client for Dr.COM / eportal campus captive portals. Protocol quirks live in per-school adapters, not in your scripts.

```
$ campus-auth status
未在线（本机 10.138.14.27，宿舍）
! 看着像宿舍（ssid），宿舍一般要加 -w cmcc，否则多半 AC 认证失败。

$ campus-auth login -w cmcc
IP 10.138.14.27  MAC AABBCCDDEEFF  账号 ,0,081425412@cmcc
服务端: 认证成功  ret_code=0
结果: 已在线
```

---

## 为什么还需要一个

校园网客户端的老项目几乎都死在同一处：**把一所学校的协议写死在主流程里**。
于是密钥算法、参数名、运营商后缀、错误码全部硬编码，第二所学校想用只能 fork 一份再改烂，
原仓库最后被 30 个不同学校的分支拖住，作者弃坑。

这个项目的约束反过来：**核心不认识任何学校**。适配层只描述差异，核心提供传输、重试、
编码、CLI 和退出码。加一所学校不改一行 core。

## 它解决什么

- **IP 一变就失效的快捷方式**：门户的密钥是 `wlan_user_ip` 的字符异或，DHCP 续租就废。
  客户端每次现场算，而不是点一个写死 IP 的 `.url`。
- **断线重连**：`watch` 只查在线列表（一次请求），确认掉线才登录，失败指数退避，
  不会把网关点成 QPS 炸弹。
- **宿舍 / 教学楼的运营商差异**：SSID 和网段决定要不要 `@cmcc` 后缀，选错就是
  `AC认证失败` —— 客户端会先提示，再把服务端的黑话翻译成人话。
- **给脚本用**：`--json` 加文档里那张退出码表，塞进计划任务和监控都不用解析中文。

## 第一步：确认这所学校用的是不是 Dr.COM

**别 clone 下来直接配。** 本项目只对 Dr.COM / eportal 有效，锐捷 ePortal、深澜 Srun、
纯 802.1X 都不通用 —— 路径可能一模一样（锐捷也用 `/eportal/portal/login`），
配半天才发现方向错，很常见。

连上学校 Wi-Fi（**必须在校园网内**，手机热点不行）后先跑：

```bash
campus-auth probe --url http://10.210.213.208:802
```

```
目标 http://10.210.213.208:802
判定: 是 Dr.COM（eportal）   置信度: 高（175 分）

  ✓ 页面 / JS 里出现 dr1003 一类回调 (+35)
  ✓ 响应含 ret_code / result 字段 (+20)
  ✓ 匿名接口回显了自己传的 callback（JSONP 可用） (+15)
  ✓ JS 里有 enc_pwd（异或加密函数） (+30)
  ✓ JS 里有 getkey（密钥派生） (+25)
  ✓ JS 里有 jsVersion 参数 (+20)
  ✓ 出现 Dr.COM / 城市热点 字样 (+15)
  ✓ 出现 wlan_user_ip 参数 (+15)
```

注意别被单条信号带偏：`dr1003` 只是**页面里出现过**才算数，因为 Dr.COM 会回显你传的
任何 callback 名，光看回显锐捷也一样。所以 `probe` 至少要求 40 分才敢下"是 Dr.COM"，
35 分只说"像"，并且会列出还缺哪些证据。

`probe` 只请求匿名接口（根页面加一个 `online_list`），**不要账号密码**，
判据是 Dr.COM 前端那套 `getkey` / `enc_pwd` / `dr1003` / `jsVersion` 指纹。
结论分档：是 / 像但证据不全 / 是锐捷 / 是深澜 / 没认出来；
`--json` 给机器读，退出码 0 命中、1 未命中、3 探不到（多半不在校园网）。

探不到或判成别的，就别按 `huuc` 抄了，先确认门户类型：

| probe 说 | 怎么办 |
| --- | --- |
| 是 Dr.COM | 抄 `huuc` 起适配层，改 `base_url`、路径、密钥函数 |
| 像 Dr.COM，证据不全 | 手动 F12 抓一次登录请求核实，多半是内网门户换了参数名 |
| 锐捷 / 深澜 | 能改，但 `login_params` 要整个重写，工作量翻倍 |
| 没认出来 | 可能根本不是网页认证（802.1X 要装客户端），本项目不适用 |

## 安装

```bash
pip install git+https://github.com/young-ski/campus-auth
```

无第三方运行时依赖，Python ≥ 3.11。没有 pip 的机器直接用单文件：
从 Releases 下 `campus-auth.pyz`，然后 `python campus-auth.pyz status`。

## 上手

```bash
campus-auth probe                 # 0 步：先确认是 Dr.COM（见上）
campus-auth init                  # 生成 campus-auth.toml
# 编辑：填 account，password 留空
export CAMPUS_AUTH_PASSWORD='...' # Windows: setx CAMPUS_AUTH_PASSWORD "..."

campus-auth status                # 先确认能连上门户
campus-auth login -w cmcc         # 宿舍；教学楼不加 -w
campus-auth watch                 # 断线自动重连，前台跑
```

`watch` 放到开机自启里就是长期方案（Windows 计划任务 → `campus-auth watch`，
把标准输出重定向到日志文件）。

## 命令与退出码

| 命令 | 作用 |
| --- | --- |
| `probe` | 探测门户是不是 Dr.COM，不需要账号（`--url` 给地址） |
| `init` | 生成配置模板（`--force` 覆盖） |
| `adapters` | 列出内置适配层 |
| `login` / `logout` / `unbind` | 登录 / 注销 / 解除 MAC 绑定 |
| `status` | 列出在线会话，`--json` 给机器读 |
| `check` | 只判定在线与否，结果走退出码 |
| `watch` | 保活循环，`--once` 跑一轮，`--interval` 调间隔 |
| `urls` | 按当前 IP 生成 `.url` / `.desktop` 快捷方式 |

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 认证被拒 / 未在线 |
| 2 | 配置问题 |
| 3 | 环境问题（不在校园网、取不到 IP） |
| 4 | 传输失败（重试耗尽） |

## 配置

优先级：内置默认 < 配置文件 < 环境变量 < 命令行参数。

```toml
adapter = "huuc"
account = "081423456"
password = ""          # 留空则读 $CAMPUS_AUTH_PASSWORD
operator = "none"      # none / cmcc / unicom / dx
verify_tls = false     # 校园门户基本是自签证书
timeout = 20
retries = 2
interval = 120
```

配置文件查找顺序：`--config` → `$CAMPUS_AUTH_CONFIG` → `./campus-auth.toml` →
`%APPDATA%\campus-auth\config.toml` / `~/.config/campus-auth/config.toml`。

**密码别写进仓库。** `CAMPUS_AUTH_PASSWORD` 或 `--password-stdin` 都行；
`keyring` 集成在路线图里。

## 内置适配层

| 名字 | 学校 | 状态 |
| --- | --- | --- |
| `huuc` | 河南城建学院（UCLINK / UCSIG） | 实机验证 |
| `generic` | 未具名 eportal 门户 | 模板，需按学校改 |

想加自己学校，看 [`CONTRIBUTING.md`](CONTRIBUTING.md)，抄
[`example_generic.py`](src/campus_auth/adapters/example_generic.py) 就够了。
也可以不改仓库、直接从任意文件加载：

```bash
campus-auth status --adapter ./my_school.py:ADAPTER
```

## 协议要点

针对 Dr.COM eportal 一类门户，逆向自前端 `getkey` / `enc_pwd`：

- 密钥 = `wlan_user_ip` 每字符 ASCII 逐位异或，**完全由 IP 决定**
- 参数值 = `hex(ord(ch) ^ key)`，两位补零
- 账号 = `,0,` + 学号 + 运营商后缀（仅宿舍）
- `wlan_user_mac` 服务端不校验，可填全 0
- 成败一律以 `online_list` 是否出现自己 IP 为准，别信返回的 `msg`

细节见 [`src/campus_auth/crypto.py`](src/campus_auth/crypto.py) 和
[`adapters/huuc.py`](src/campus_auth/adapters/huuc.py)。

## 已知限制

- 只覆盖网页版 eportal（`/eportal/portal/*`）。走 802.1X 或专用客户端加密的学校用不了 ——
  先跑 `probe` 确认，别硬配。
- `probe` 的指纹表是 Dr.COM 与锐捷/深澜的差异，不是抓包级证据；判成"证据不全"时仍需人工核实。
- 应答里的运营商错误码只整理了城建遇到的四种，别的学校会落到通用提示。
- 不做"绕过计费"，只是替你把官方的网页登录动作自动化。
- 门户升级会改参数名，适配层跟着改；`generic` 模板就是为此留的。

## 免责

非官方项目，与学校和 Dr.COM 均无关系。协议来自公开前端代码和本机抓包，
不含任何校内凭据。密码只在内存和你的配置文件里，不往第三方发。

## 许可证

MIT。
