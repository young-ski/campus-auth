# campus-auth

**校园网门户认证客户端。** 一行命令登录，断线自动重连。Dr.COM / eportal、锐捷、深澜三种协议都内置，
学校差异全部塞进可插拔的适配层。

> A CLI client for campus captive portals (Dr.COM / Ruijie / Srun). Protocol quirks live in adapters, not in your scripts.

```
$ campus-auth probe
判定: 是 Dr.COM（eportal）   置信度: 高（175 分）

$ campus-auth login -w cmcc
IP 10.138.14.27  MAC AABBCCDDEEFF  账号 ,0,081456789@cmcc
服务端: 认证成功  ret_code=0
结果: 已在线
```

上面这些学号、MAC、IP 都是编的，不用对号入座。

| 协议 | 适配层 | 状态 |
| --- | --- | --- |
| Dr.COM / eportal（`wlan_user_ip` + 异或） | `huuc` | **实机验证** |
| 锐捷 `InterFace.do`（POST 表单 + 204 劫持发现） | `ruijie` | 未实机（假门户端到端通过） |
| 深澜 `srun_portal`（challenge + XXTEA + chksum） | `srun` | 未实机（假门户端到端通过） |
| 未具名 eportal | `generic` | 模板 |

"未实机"= 按公开实现和抓包样式写的，协议细节有测试钉住，但没在真实设备上跑过。
第一次用请当作实验，跑不通请开 Issue 带打码样本。

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

## 第一步：先确认门户是哪一家

**别 clone 下来直接配。** 锐捷和 Dr.COM 的登录路径可以一模一样，配半天才发现协议不对很常见。

连上学校 Wi-Fi（**必须在校园网内**，手机热点不行）后先跑 `probe`：

```bash
campus-auth probe                 # 用当前适配层的地址
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

注意别被单条信号带偏：`dr1003` 只有**页面里出现过**才算数，因为 Dr.COM 会回显你传的
任何 callback 名，光看回显锐捷也一样。所以 `probe` 至少要求 40 分才敢下"是 Dr.COM"，
35 分只说"像"，并且会列出还缺哪些证据。

`probe` 只请求匿名接口，**不要账号密码**；`--json` 给机器读，退出码 0 命中、1 未命中、
3 探不到（多半不在校园网）。判定结果直接对应到该用哪个适配层：

| probe 说 | 用这个 | 备注 |
| --- | --- | --- |
| 是 Dr.COM | `--adapter huuc` 改名复用 | 主要改 `base_url`、路径、密钥函数 |
| 像是 Dr.COM，证据不全 | 先别动手 | F12 抓一次真登录请求核实 |
| 是锐捷 | `--adapter ruijie` | 需要 `--url` 给门户页或 204 地址 |
| 是深澜 | `--adapter srun` | 需要 `--url` 指到登录页（要读 `ac_id`） |
| 没认出来 | 可能根本不是网页认证 | 802.1X 得装专用客户端，本项目不适用 |

## 安装

```bash
pip install git+https://github.com/young-ski/campus-auth
```

无第三方运行时依赖，Python ≥ 3.11。没有 pip 的机器直接用单文件：
从 Releases 下 `campus-auth.pyz`，然后 `python campus-auth.pyz status`。

## 上手

```bash
campus-auth probe                 # 0 步：先确认门户类型（见上）
campus-auth init                  # 生成 campus-auth.toml
# 编辑：adapter 填 probe 判出来的那个；account 填学号；password 留空
export CAMPUS_AUTH_PASSWORD='...' # Windows: setx CAMPUS_AUTH_PASSWORD "..."

campus-auth status                # 先确认能连上门户
campus-auth login                 # Dr.COM 宿舍要加 -w cmcc，教学楼不加
campus-auth watch                 # 断线自动重连，前台跑
```

锐捷和深澜要多一个门户地址（它们没有固定域名，且深澜要读页面里的 `ac_id`）：

```bash
# 锐捷：可以给门户页，也可以给 204 劫持地址，客户端自己找 InterFace.do
campus-auth login --adapter ruijie --url http://10.20.30.1/eportal/index.jsp?wlanuserip=10.1.2.3
# 深澜：给登录页
campus-auth login --adapter srun --url http://10.20.30.1/
```

## 开机自启

`watch` 放前台只是临时用，长期靠 install 装成登录自启：

```bash
campus-auth install --dry-run     # 先看它要写什么、跑什么
campus-auth install               # Windows: HKCU\...\Run + 一个 .cmd 包装
                                  # Linux:   systemd --user unit
                                  # macOS:   ~/Library/LaunchAgents/*.plist
campus-auth uninstall             # 停掉并删干净
```

密码不会被代管：自启进程不继承你当前 shell 的环境变量，**密码得放进钥匙串
或配置文件**，install 发现两处都没有会提醒。日志写在系统的 state 目录
（Windows `%LOCALAPPDATA%\campus-auth\watch.log`，其他平台 `~/.local/state/campus-auth/`）。

## 命令与退出码

| 命令 | 作用 |
| --- | --- |
| `probe` | 探测门户类型，不需要账号（`--url` 给地址） |
| `init` | 生成配置模板（`--force` 覆盖） |
| `adapters` | 列出内置适配层与验证状态 |
| `login` / `logout` / `unbind` | 登录 / 注销 / 解除 MAC 绑定（深澜暂不支持 `unbind`） |
| `status` | 列出在线会话，`--json` 给机器读 |
| `check` | 只判定在线与否，结果走退出码 |
| `watch` | 保活循环，`--once` 跑一轮，`--interval` 调间隔 |
| `install` / `uninstall` | 把 `watch` 装成登录自启 / 卸掉（`--dry-run` 只打印） |
| `password` | 密码存进/删出系统钥匙串（`--forget` 删） |
| `urls` | 按当前 IP 生成 `.url` / `.desktop` 快捷方式（POST 类只有地址） |

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 认证被拒 / 未在线 |
| 2 | 配置问题 |
| 3 | 环境问题（不在校园网、取不到 IP） |
| 4 | 传输失败（重试耗尽） |

`--check-url` 可以换掉锐捷默认的 204 探测地址（`connect.rom.miui.com`），
有些学校会把这个域名也拦掉 —— 换成自己的 `generate_204` 或校园网内任意 204 地址。

## 配置

优先级：内置默认 < 配置文件 < 环境变量 < 命令行参数。

```toml
adapter = "huuc"       # probe 判出来哪个填哪个：huuc / ruijie / srun
account = "081456789"
password = ""          # 留空则读 $CAMPUS_AUTH_PASSWORD，再不行读系统钥匙串
operator = "none"      # none / cmcc / unicom / dx（仅 Dr.COM 系有运营商后缀）
base_url = ""          # 锐捷/深澜必填，指到门户页
verify_tls = false     # 校园门户基本是自签证书
timeout = 20
retries = 2
interval = 120
# check_url = ""       # 锐捷判定在线用的 204 地址，默认 connect.rom.miui.com
```

配置文件查找顺序：`--config` → `$CAMPUS_AUTH_CONFIG` → `./campus-auth.toml` →
`%APPDATA%\campus-auth\config.toml` / `~/.config/campus-auth/config.toml`。

**密码别写进仓库。** 优先级从高到低：`$CAMPUS_AUTH_PASSWORD` → 配置文件 → 系统钥匙串。
推荐钥匙串（Windows 凭据管理器 / macOS Keychain / Linux Secret Service）：

```bash
pip install "campus-auth[keyring]"   # 只装这个功能
campus-auth password                 # 看有没有存
campus-auth password -p '...'        # 存（也可以 echo -n '...' | campus-auth password）
campus-auth password --forget        # 删
campus-auth login --remember         # 或者登录成功时顺手存
```

没装 `keyring`、或后端不可用（headless Linux 常见）时全部自动退回配置文件/环境变量。

锐捷注销要用的 `userIndex` 会缓存到配置目录的 `state.json`（不含密码，12 小时过期），
`$CAMPUS_AUTH_STATE` 可以把路径换掉。

## 内置适配层

| 名字 | 门户 | 状态 | 需要 |
| --- | --- | --- | --- |
| `huuc` | 河南城建学院（Dr.COM，UCLINK / UCSIG） | 实机验证 | 无（默认地址） |
| `ruijie` | 锐捷 ePortal | 未实机 | `--url` 或 `--check-url` |
| `srun` | 深澜 Srun | 未实机 | `--url` 指向登录页 |
| `generic` | 未具名 eportal | 模板 | 按学校改 |

`ruijie` / `srun` 的协议细节都有测试钉住（深澜的 XXTEA 用上游测试向量对过），
`tools/fake_portal.py` 能起同款假门户做端到端（深澜可加 `--variant` 切两代编码）。
但没在真实设备上跑过 —— 第一次当实验用，报错请开 Issue。

想加自己学校，看 [`CONTRIBUTING.md`](CONTRIBUTING.md)，抄
[`example_generic.py`](src/campus_auth/adapters/example_generic.py) 就够了。
也可以不改仓库、直接从任意文件加载：

```bash
campus-auth status --adapter ./my_school.py:ADAPTER
```

## 协议要点

**Dr.COM**（逆向自前端 `getkey` / `enc_pwd`）：

- 密钥 = `wlan_user_ip` 每字符 ASCII 逐位异或，**完全由 IP 决定**
- 参数值 = `hex(ord(ch) ^ key)`，两位补零
- 账号 = `,0,` + 学号 + 运营商后缀（仅宿舍）
- `wlan_user_mac` 服务端不校验，可填全 0
- 成败一律以 `online_list` 是否出现自己 IP 为准，别信返回的 `msg`

**锐捷**：`InterFace.do` 走 POST 表单，`queryString` 取自 204 劫持页 URL 并二次编码，
在线与否看 `generate_204` 是否 204。注销、解绑是同一个 `InterFace.do`，把 `method` 换成
`logout` / `unbind`：注销只认登录时拿到的 `userIndex`（会缓存到 `state.json`，见上节），
解绑认学号，跨进程也能跑。

**深澜**：`get_challenge` 取一次性 challenge，`password` 传 `{MD5}` + HMAC-MD5，
`info` 传 `{SRBX1}` + XXTEA(json) 的深澜 base64，再用 sha1 对整串签名成 `chksum`，
在线的判据是 `rad_user_info` 的 `error` 字段。

新版门户的 `info` 换成 `{SRBX2}` + **标准** base64（`srun_bx2`），从登录页脚本里的
`enc_ver` 自动认，认不出按 `srun_bx1`。

细节见 [`crypto.py`](src/campus_auth/crypto.py)、[`crypto_srun.py`](src/campus_auth/crypto_srun.py)
和三个适配层。

## 已知限制

- 只覆盖网页认证门户。走 802.1X 或专用客户端加密的学校用不了 —— 先跑 `probe`，别硬配。
- `ruijie` / `srun` **未实机验证**，各校版本差异大，可能需要改适配层。
- 深澜的 `srun_bx2` 是照公开资料实现的，只在假门户（`--variant srun_bx2`）上过过；
  真门户若用别的写法声明 `enc_ver`，会识别不出来而退回 `srun_bx1`，表现为 `info` 被拒。
- 锐捷的 `unbind` 打的是 `InterFace.do?method=unbind`，只在假门户上验过：各校版本叫别的 method
  时会回 `method 不对`，改 [`ruijie.py`](src/campus_auth/adapters/ruijie.py) 的 `UNBIND_METHOD` 即可。
  有的版本还要求带密码，`unbind` 时给个 `-p` 就会带上。
- `install` 在 Windows 上写 `HKCU\...\Run`；被组策略禁掉自启的机器会装不上，
  失败时照 `--dry-run` 打印的那行命令手动加。
- 钥匙串要靠 `keyring` 和可用的后端；headless Linux 上常常没有，会给提示并退回配置文件。
- 深澜的 `unbind` 还没实现：eportal 那套通用解绑路径在深澜门户上只会取回登录页 HTML，
  命令会以 4 退出。
- 锐捷的 `logout` 必须是本机 `login` 过之后的 12 小时内、且 IP 没变 —— `userIndex` 缓存在
  `state.json`，丢了就只能等门户自己超时，或者用 `unbind` 解掉绑定再登。
- POST 类适配层（锐捷）的 `urls` 快捷方式只带地址、没有表单体，点开会是错误页 —— 用 `login`。
- `probe` 的指纹表是判断"哪一家"，不是抓包级证据；判成"证据不全"时仍需人工核实。
- 应答里的运营商错误码只整理了城建遇到的四种，别的学校会落到通用提示。
- 不做"绕过计费"，只是替你把官方的网页登录动作自动化。
- 门户升级会改参数名，适配层跟着改；`generic` 模板就是为此留的。

## 免责

非官方项目，与学校、Dr.COM、锐捷、深澜均无关系。协议来自公开前端代码和本机抓包，
不含任何校内凭据。密码只在内存和你的配置文件里，不往第三方发。

## 许可证

MIT。
