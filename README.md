# campus-auth

[![PyPI](https://img.shields.io/pypi/v/campus-auth)](https://pypi.org/project/campus-auth/)
[![Python](https://img.shields.io/pypi/pyversions/campus-auth)](https://pypi.org/project/campus-auth/)
[![CI](https://github.com/young-ski/campus-auth/actions/workflows/ci.yml/badge.svg)](https://github.com/young-ski/campus-auth/actions/workflows/ci.yml)

**Dr.COM / eportal 校园网门户认证客户端。** 一行命令登录，断线自动重连。密钥算法、参数名、
运营商后缀全部收在工具里，你不用再点一个 IP 一变就失效的快捷方式。

> A CLI client for Dr.COM/eportal campus captive portals (Chinese campus networks).

```
$ campus-auth login -w cmcc
IP 10.138.14.27  MAC AABBCCDDEEFF  账号 ,0,081456789@cmcc
服务端: 认证成功  ret_code=0
结果: 已在线
```

文里的学号、MAC、IP 都是编的。

| 门户 | 适配层 | 状态 |
| --- | --- | --- |
| Dr.COM / eportal（`wlan_user_ip` + 异或） | `huuc` | **实机验证**（河南城建学院） |
| 其它 Dr.COM 门户 | `generic` | 模板，照它改 |

**范围只有 Dr.COM / eportal。** 锐捷（`InterFace.do`）和深澜（`srun_portal`）不随包提供：
维护者拿不到真机，不想一直挂着“未实机”。`probe` 仍然能认出它们，认出来会直接告诉你换工具。

---

## 为什么还需要一个

校园网客户端的老项目大多死在同一处：**把一所学校的协议写死在主流程里**，第二所学校只能 fork
一份改烂，原仓库最后被几十个分支拖住。这里的约束反过来：**核心不认识任何学校**，一所学校的
差异只写在适配层里，加学校不改 core。

## 它解决什么

- **IP 一变就失效的快捷方式**：门户的密钥是 `wlan_user_ip` 的字符异或，DHCP 续租就废。
  客户端每次现场算。
- **断线重连**：`watch` 先查在线列表（一次请求），确认掉线才登录，失败指数退避，
  不会把网关点成 QPS 炸弹。
- **宿舍 / 教学楼的运营商差异**：SSID 和网段决定要不要 `@cmcc` 后缀，选错就是
  `AC认证失败` —— 客户端会先提示，再把服务端的黑话翻译成人话。
- **给脚本用**：`--json` 加下面那张退出码表，塞进计划任务和监控都不用解析中文；字段有 schema 版本和稳定性承诺，见 [`docs/json.md`](docs/json.md)。

## 三步上手

必须在校园网内（手机热点不行）。

```bash
campus-auth probe                          # 1. 先确认是 Dr.COM，不是别的门户
campus-auth init                           # 2. 生成配置模板
campus-auth password                       # 3. 存密码（不回显，进系统钥匙串）
```

`init` 之后按提示改 `account`，然后：

```bash
campus-auth status     # 自检：没配好会直接指出来
campus-auth login      # 宿舍网段加 -w cmcc，教学楼不加
campus-auth watch      # 断线自动重连，前台跑
```

`status` 会把“门户里有会话”和“会话是你自己的”分开说 —— 前者可能只是上一位用户还没掉线。

## 第一步的 probe

`probe` 只请求匿名接口，**不要账号密码**；只从校园网内有效。默认会跟着劫持页跳一次，不想跟加 `--no-follow`。

```
$ campus-auth probe --url http://10.210.213.208:802
判定: 是 Dr.COM（eportal）   置信度: 高（155 分）

  ✓ 页面 / JS 里出现 dr1003 一类回调 (+35)
  ✓ JS 里有 enc_pwd（异或加密函数） (+30)
  ✓ JS 里有 getkey（密钥派生） (+25)
  ✓ 出现 wlan_user_ip 参数 (+20)
  ...
```

判定不是看一条信号：`dr1003` 只有**页面里出现过**才算数（Dr.COM 会回显你传的任何 callback），
权重按“哪家独有”排，一家要过 35～40 分**并且领先第二名 10 分**才敢下结论，咬得紧就只说
“像”，并列出还缺哪些证据。

| probe 说 | 怎么办 |
| --- | --- |
| 是 Dr.COM | 用 `huuc` 或 `generic` 起配置，只改 `base_url` 与密钥/参数 |
| 像是 Dr.COM，证据不全 | 别急着配：F12 抓一次真登录请求核实参数名 |
| 是锐捷 / 深澜 | 本项目不覆盖，换对应工具 |
| 没认出来 | 可能不是网页认证：路由器自带页、802.1X 都长这样 |

退出码：0 命中、1 未命中、2 地址格式错、3 探不到（多半不在校园网）。

## 安装

```bash
pip install campus-auth
pip install "campus-auth[keyring]"   # 可选：把密码交给系统钥匙串
```

默认无第三方运行时依赖，`keyring` 是唯一的可选 extra。Python ≥ 3.11。
想跟未发布的主干，也可以装 git：

```bash
pip install "campus-auth @ git+https://github.com/young-ski/campus-auth"
```

没有 pip 的机器用单文件：从 Releases 下 `campus-auth.pyz`，`python campus-auth.pyz status`。

## 配置

优先级：内置默认 < 配置文件 < 环境变量 < 命令行参数。配置文件依次找
`--config` → `$CAMPUS_AUTH_CONFIG` → `./campus-auth.toml` → 系统配置目录。

```toml
adapter = "huuc"       # 换成你自己学校的适配层
account = "081456789"  # 学号，纯数字，别带 @ 后缀
password = ""          # 留空则读 $CAMPUS_AUTH_PASSWORD，再不行读系统钥匙串
operator = "none"      # none / cmcc / unicom / dx，宿舍才需要
base_url = ""          # 留空用适配层里的地址
verify_tls = false     # 校园门户基本是自签证书
timeout = 20
retries = 2
interval = 120
```

**密码别写进仓库。** 优先级从高到低：`$CAMPUS_AUTH_PASSWORD` → 配置文件 → 系统钥匙串。
推荐钥匙串（Windows 凭据管理器 / macOS Keychain / Linux Secret Service）：

```bash
campus-auth password          # 交互式输入；管道里则读一行
campus-auth password --show   # 只看有没有存
campus-auth password --forget # 删
campus-auth login --remember  # 或者登录成功时顺手存
```

没装 `keyring` 或后端不可用（headless Linux 常见）时自动退回配置文件/环境变量。

## 开机自启

```bash
campus-auth install --dry-run   # 先看它要写什么、跑什么
campus-auth install             # Windows: HKCU\...\Run + .cmd；Linux: systemd --user；macOS: LaunchAgent
campus-auth uninstall           # 停掉并删干净
```

自启进程不继承你当前 shell 的环境变量，密码得放进钥匙串或配置文件，install 会提醒。
日志在系统 state 目录（Windows `%LOCALAPPDATA%\campus-auth\watch.log`），`watch` 自己按
1 MiB 轮转；三条实现都带自动重启，崩了会自己回来。

## JSON 输出

`--json` 的每个对象都带 `"schema": 1`，同一版本内只增字段、不删不改。
字段表、示例和稳定性约定在 [`docs/json.md`](docs/json.md)，机器可读版在
[`docs/json.schema.json`](docs/json.schema.json)（CI 会拿真实输出对一遍）。

## 命令与退出码

| 命令 | 作用 |
| --- | --- |
| `probe` | 探测门户类型，不需要账号（`--url` 给地址） |
| `init` | 生成配置模板（`--force` 覆盖） |
| `adapters` | 列出内置适配层与验证状态 |
| `login` / `logout` / `unbind` | 登录 / 注销 / 解除 MAC 绑定 |
| `status` | 列出门户会话，标出哪条是你自己的；`online` 指你自己、`any_online` 指门户里有任何会话 |
| `check` | 只判定在线与否，结果走退出码 |
| `watch` | 保活循环，启动打摘要、每轮带耗时；`--once` 跑一轮，`--log` 同时落盘（自动轮转） |
| `install` / `uninstall` | 把 `watch` 装成登录自启 / 卸掉（`--dry-run` 只打印） |
| `password` | 密码存进/删出系统钥匙串（`--show` 看状态，`--forget` 删） |
| `urls` | 按当前 IP 生成 `.url` / `.desktop` 快捷方式（内含可还原的密码） |

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 认证被拒 / 未在线 |
| 2 | 配置问题（缺字段、适配层不存在、URL 写错） |
| 3 | 环境问题（不在校园网、取不到本机 IP） |
| 4 | 传输问题（超时、连接被拒、重试耗尽） |

## 加一所学校

`generic` 就是模板：复制成 `<学校代号>.py`，按 F12 抓到的真请求改 `base_url`、参数名、
密钥函数，再到 `adapters/__init__.py` 登记。步骤和验收清单见
[`CONTRIBUTING.md`](CONTRIBUTING.md)，那里也写了哪些东西不能提交（真实学号、密码、MAC）。

## 已知限制

- 只覆盖 Dr.COM / eportal 的网页认证。锐捷、深澜、802.1X、专用客户端加密的学校都用不了。
- `probe` 是判断“哪一家”，不是抓包级证据；判成“证据不全”时仍需人工核实。
- **TLS 默认不校验证书**（校园门户清一色自签）。想校验就 `--verify-tls`，遇到自签会失败。
- `.url` / `.desktop` 快捷方式里的密码是 IP 异或的密文，而 IP 就在同一个 URL 里 ——
  **等于明文**，分享前留意。报错里的 URL 默认把密码打成 `ab…yz`，要原文加
  `--show-secrets`。
- `state.json` 只存学号、IP、会话索引，不含密码；POSIX 下权限 0600，Windows 靠目录 ACL。
- 门户升级会改参数名，适配层跟着改；`generic` 就是为此留的。

变更历史见 [`CHANGELOG.md`](CHANGELOG.md)。

## 免责

非官方项目，与学校、Dr.COM 均无关系。协议来自公开前端代码和本机抓包，不含校内凭据。
密码流经：内存、系统钥匙串（若启用）、配置文件（若你写了）、`.url` 文件与报错里的密文。

## 许可证

MIT。
