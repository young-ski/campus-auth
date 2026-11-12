# 变更记录

只记对本仓库使用者有影响的东西。版本号跟 `pyproject.toml` 走，日期在打 tag 时补。

## 1.7.6（2026-11-13）

### 修复

- **探测 Python 时可能卡死**：`-c` 的脚本以前拼在一个变量里，变量没展开就变成裸的
  `py -3.13` —— 进交互式 REPL、一直等输入（同学实测卡了 10 分钟）。现在脚本内联，
  且所有探测调用都带 `<nul`，任何情况下都不会停在等输入上
- **从压缩包装的自启跑不起来**：`install` 生成的是 `python -m campus_auth watch`，可是
  pyz 里的包没装进 site-packages，装完一跑就 import 失败。现在检测到自己在 pyz 里跑时，
  改成 `python <pyz> watch`，并把 pyz 复制到配置目录再指过去 —— 删掉解压出来的文件夹也不失效
- **重复卸载会报错**：注册表项或文件本来就不在时，`uninstall` 现在照常成功并提示一句，
  不再退 2 或抛 traceback
- `install` 的密码来源检查从此前只认「空密码」扩展到「密码只在环境变量里」

### 变更

- **`setup` 不再打开记事本**：学号和密码都在窗口里问，问完直接写配置。学号只认数字，
  手快把 `@cmcc` 抄进来的会自动取前面的数字；提示语里也不再教「别带 @」

### 文档

- 安装说明补「双击没反应 / 智能应用控制拦住」的处理：右键属性解除锁定，或
  `Unblock-File`，以及最后的系统开关在哪

## 1.7.5（2026-11-12）

### 修复

- **装了 Python 3.12，`install.cmd` 仍说找不到**：旧脚本只试 `py -3` 和 PATH 上的 `python`。
  现在按顺序试 `py -3.13`…`-3.10`、PATH、注册表（`PythonCore` 的 `ExecutablePath`）、
  以及 python.org / uv / conda / scoop 的默认目录——「装了但没加 PATH」和 uv 装出来的
  3.12 都能找到。仍找不到时不再只给一句「没装」，而是打印 `where python` / `py -0p` 的现场，
  并支持显式指定：`install.cmd "C:\...\python.exe"`
- **Python 3.10 也能用了**：代码里唯一的 3.11 依赖是 `tomllib`，内置一份 `tomli`（MIT，
  保留上游 LICENSE）给 3.10 兜底；`requires-python` 降到 `>=3.10`，CI 矩阵补 3.10

### 文档

- 安装说明写清「3.10 或更新」、查找顺序，以及找不到时怎么把现场发出来

## 1.7.4（2026-11-09）

### 新增

- **`setup`**：一条命令做完首次配置 —— 先讲清风险，再写配置、让人填学号、存密码
  （钥匙串优先，进不去就写配置文件）、当场登一次、最后问要不要开机自启。重跑（`--force`）
  会沿用的学号，不再反复问
- **发给同学的 Windows 压缩包**：`campus-auth-<版本>-win.zip`，内含 `install.cmd`
  （查 Python、核 SHA256、调 `setup`）、`install-guide.txt`、`disclaimer.txt`。发版自动挂到 Release
- 配置默认位置统一成 `~/.config/campus-auth/config.toml` / `%APPDATA%\campus-auth\config.toml`，
  和配置文件发现顺序的最后一项是同一个文件；删掉解压目录不影响自启

### 修复

- **`campus-auth.pyz` 永远退 0**：`zipapp` 的 `main=` 生成的入口不调 `sys.exit`，退出码契约
  在单文件形态上整个失效（计划任务与 `check` 都靠它）。改成自己写入口
- `cli.main` 里 `errno 22` 一律当断管：会写文件的命令自己 `catch OSError`，`init` 写不进去
  时退 2 并说明
- `install` 认不出「密码只来自环境变量」，装完 watch 必失败：现在 dry-run 就警告

### 文档

- README 安装段分成「不会命令行的同学」和「会命令行」，前者就是压缩包那条路，
  并写明装之前要先连热点/流量
- CONTRIBUTING 发布段补压缩包的生成与自检要求

## 1.7.3（2026-11-09）

### 修复

- **本校门户上 `probe` 判成「锐捷 / 没认出来」**：首页是 Vue SPA，`<script src=...>` 不带引号，
  只认引号的旧正则一个 JS 都抓不到，`enc_pwd` / `getkey` 等独有特征永远不命中。现在三种属性
  写法都认，并补了两条固定 JS 候选（404 桩会识别跳过）
- **已在线时 `probe` 直接失败**：劫持页捞不到地址就以 2 退出。现在先退回适配层地址再探，
  真没地址才报错；会话接口的 `online_session` / `online_time` 也算独有证据，结论里点明「已在线」
- **只收 HTTPS 的门户按 `http://<旧IP>` 探会 400**：现在自动换 https 再探一遍，结论里报实际用的地址
- `probe --no-discover` 把 `--adapter` 整个丢掉，一直读配置文件里的适配层
- 拒绝登录后仍轮询 3 次在线状态：真实门户要 7.1 秒。现在被拒只确认一次，同一用例 0.4 秒
- `AC999` 等门户拒绝码没翻译，只回「ret_code=2，原文 AC999」
- `init -o` 写到非法路径（Windows 的 `?`）时 exit 0、无文件、无输出：现在报「写不了」并退 2
- 钥匙串不可用时 `password` 只说「去装 keyring」：现在给配置文件和 `$CAMPUS_AUTH_PASSWORD` 两条
  可走的路，并打出能直接抄进配置的那一行
- `install` 不提醒密码只来自环境变量：自启不继承 shell env，装完 watch 必失败。现在 dry-run
  就会警告
- `--show-secrets` 只能放在子命令前，放后面被 argparse 打回
- 控制台按 cp936 解码，强推 UTF-8 会让中文变「置信�?」：tty 保留控制台编码，只有重定向才统一成 UTF-8

### 文档

- 首屏改成河南城建学院口径，外校与适配层相关内容下移
- `--url http://<门户IP>` 的示例与引导改成 https；`probe` 退出码表补 4
- 新增「免责与风险」：校内无明确规定、自担风险、密码流向、失效时怎么办
- 修 `state.json` 与 `schtasks` 两处与实现不符的说明

## 1.7.2（2026-10-28）

### 修复

- `watch` 的每轮时间戳只有 `HH:MM:SS`，日志跨夜就定位不了：改成带日期
- `probe --retries` 一直挂在 help 里却没人用：接进取样，失败样本按退避重试
- 补两处回归断言：登录确认成功后不再白等（本来如此，但没测过）

## 1.7.1（2026-10-28）

### 修复

- Release 说明在标题带日期后整段切不出来，回退成了「v1.6.0」这样的空壳：切分逻辑抽成
  `tools/release_notes.py`，按前缀匹配并要求版本号后不是数字；已回填 1.6.0 / 1.7.0 的说明

## 1.7.0（2026-10-28）

### 新增

- 支持第三方适配层包：在 `.dist-info` 里把名字注册到 `campus_auth.adapters` entry point 组，
  `--adapter <名字>` 就能选到；同名时内置优先。`adapters` 列表也一并列出
- README 首屏加英文说明；`docs/schools.md` 补收录标准

## 1.6.0（2026-10-28）

### 新增

- `new-adapter <代号>`：生成可立即加载的适配层骨架，带必改清单、`status="未验证"` 与验连通命令
- 适配层的 `status` 默认改成「未验证」（以前一出生就自称已验证），`huuc` 显式标「已验证」

## 1.5.0（2026-10-28）

### 新增

- `probe` 不给 `--url` 时会从校园网劫持页里找门户地址（两个公开探针，`--no-discover` 可关）。
  已经在线的网络捞不到东西，会明确让你改用 `--url`
- `init --url` 把门户地址直接写进配置；`init` 同时打印它选的适配层与地址，适配层状态不是
  「已验证」时会提示先 probe
- README 首屏补「不是本校怎么办」的 `--adapter generic --url` 分支
- `doctor` 命令：一次打出排障要的版本、配置路径、适配层、连通性与探测结论，密码只报来源
- `SECURITY.md`（私下通道 + 打码规则 + 哪些是设计取舍）、PR 模板、bug 模板的安装方式与
  `probe --json` 字段
- CI 新增 Windows / macOS 的 install 真跑作业：装完去注册表 / launchd 里核实，卸载后断言干净

## 1.4.0（2026-10-28）

**破坏性**：`--json` 的 stdout 现在是纯 JSON，面向人的文案全部改走 stderr。`init` /
`adapters` / `urls` / `password` / `install` / `uninstall` 不再接受 `--json`（会直接报
多余参数，退出码 2）。靠人读输出做管道的用法不受影响，只有 `--json` 的消费方需要改。

### 新增

- `--adapter` 现在也能直接给文件路径（`路径.py:ADAPTER`），`module:attr` 的模块名照旧。
  配套 [`docs/schools.md`](docs/schools.md)：社区适配层目录，放外面跑通也登记得进去

### 发布

- `publish.yml` 现在先跑测试、校验版本三方一致（tag / `pyproject.toml` / `__init__`），
  再构建、上传、自己建 Release 并挂上 pyz 与 `SHA256SUMS`。`workflow_dispatch` 不再能
  整段绕过版本校验。
- 单文件 pyz 改由 `tools/build_zipapp.py` 构建，排除 `__pycache__` / `*.pyc` / `*.egg-info`：
  402 KB → 53 KB，条目 71 → 30。
- 新增 `tools/check_version.py`；CI 的冒烟步骤改用同一个打包脚本，避免发布与 CI 各走一套。

### 修复

- `watch` 在门户已判不在线后仍因 DNS 通顺直接返回、一次登录都不发（校园门户劫持 DNS，
  这条快速路径恒为真）。现在以门户会话列表为准，DNS 只在被拒后用于归因；连续 3 轮
  「被拒 + DNS 通」按健康处理，避免门户会话接口坏掉时退避到 8 倍间隔
- Windows 自启装完即崩：`pythonw` 下 `sys.stdout is None`，`Tee` 未判空。现在丢弃空流并把
  日志顶上，`install` 生成的 `.cmd` 不再每 31 秒撞一次
- 超过 80 字符的密码密文会漏出尾巴（掩码正则写了 `{1,80}` 上限）
- `login --json` 在已在线时一个 JSON 都不输出，其余路径的人话还混在 stdout；`probe --json`
  失败时同理
- `check --json` 忽略 flag、直接吐 `online` / `offline`
- `probe` 失败一律退 3 并提示「先连校园网」；传输错误现在按约定退 4
- `probe` 会把通用 nginx 登录页判成「是 Dr.COM」：`wlan_user_ip` + `result` + nginx 三条谁都有
  的信号刚好凑过门槛。nginx 信号减半、门槛 40→55，且判成 Dr.COM 必须命中 `enc_pwd` / `getkey`
- 配置里写 `account = 81456789`（不加引号）会 `TypeError` 并以 70 退出：字符串字段统一 `str()`
- 端口越界（`http://h:99999`）以 70 + traceback 退出：现在归为配置错 2
- `local_mac` 用子串判 IP，查 `10.138.14.2` 会命中 `10.138.14.27` 那块、返回别的网卡的 MAC；
  改为按 IPv4 行精确匹配，精确不到再退回子串
- 非 ASCII 密码会发出与浏览器不同的密文：`validate` 直接拦下（退出码 2），提示改 ASCII
- 钥匙串查询早于命令行覆盖：`login -a 学号` 拿空账号去查、永远查不到，配置里是另一个号时
  还会静默用错密码。改为应用 overrides 之后再查
- `--mac` 只数长度，`ZZZZZZZZZZZZ` 也放行：改成正则校验 12 位十六进制
- 两个 `watch --log` 写同一个文件时，轮转里的 `replace` 会抛 WinError 32 并带崩进程：
  写入与轮转都改成尽力而为（失败留到下次重开），日志器不再打死主循环
- 配置里 `verify_tls = true` 之后命令行无法关掉：`--verify-tls` 改成双向，可用 `--no-verify-tls`
- `password --forget` 在后端报错时照样打印「已删除」：改为报「删不掉」并以 3 退出；
  `keyring.backends.fail` 也不再算「可用」
- `probe --url` 写错时给的是「先连校园网」且退出码 3：地址类错误现在退 2，只提示地址怎么写

### 整理

- 清掉死代码与假 docstring：`portal.py` 队尾不可达的兜底、只被测试调用过的 `iter_retry_delays`
  （现已接进重试）、`cli.py` 里「实现在 commands.py」的说法、schema 校验器的 `oneOf` 说法
- `CHANGELOG` 里整块重复的 1.3.0 / 1.2.1 / 1.2.0 已删，被拆成两半的 1.1.0 合并回一节
- 500/502/504 不重试（只认 429/503），一次代理抖动就废掉整次登录
- `Retry-After` 头名大小写敏感：小写 `retry-after: 20` 被丢掉、走成 2 秒。头名统一小写化，
  取值也忽略大小写

## 1.3.0

### 新增

- `--json` 输出有了 schema：每个对象带 `"schema": 1`，字段说明与稳定性承诺写在
  [`docs/json.md`](docs/json.md)，机器可读版是 [`docs/json.schema.json`](docs/json.schema.json)，
  `tests/test_json_schema.py` 会拿真实输出逐条校验
- 配置 / 环境类错误也输出 JSON 错误对象（以前只有认证类错误才输出）

### 变更

- `status --json` 缺账号时 stdout 只剩 JSON，不再先打一行人读提示
- 同一 schema 版本内只增字段、不改语义；破坏性改动会加 schema 版本

## 1.2.1

### 修复

- CI 挂在一处版本相关的断言：argparse 在 3.11/3.12 把 `-a 学号, --account 学号` 渲染成
  另一副样子，测试只认长名了

## 1.2.0

**破坏性**：参数收敛到各命令真正用得上的那些 —— 例如 `status -p`、`probe --password-stdin`
现在会报"多余参数"。脚本里带上的多余 flags 要去掉。

### 新增

- `watch` 启动时打一行摘要（适配层 / 门户 / 账号 / IP / 间隔 / 日志），每轮带耗时；
  `--json` 换成一个 `event: start` 摘要对象和带 `elapsed_ms` 的 cycle 对象
- `probe` 跟了劫持跳转就在结论里点明落在哪个 host；`--no-follow` 可关掉跟随

## 1.1.0

### 新增

- `install` / `uninstall`：把 `watch` 装成登录自启（Windows `HKCU\...\Run` + `.cmd`，
  Linux `systemd --user`，macOS LaunchAgent），`--dry-run` 只打印；三条实现都带自动重启
- `watch --log`：自己写日志并按 1 MiB 轮转，留一份 `.1`
- 可选 `keyring`：`password` 命令存取（交互式隐藏输入、`--show` 看状态）、
  `login --remember` 顺手存；密码解析顺序变成 `$CAMPUS_AUTH_PASSWORD` > 配置文件 > 钥匙串
- 深澜 `srun_bx2` 变体：按页面里的 `enc_ver` 自动切换 `{SRBX2}` + 标准 base64
- 锐捷解绑：`InterFace.do?method=unbind`，`userIndex` 落盘 12 小时支撑跨进程注销

### 修复

- systemd unit 写到了 `systemctl` 不认的目录（`~/.config/campus-auth/systemd/user`）
- `Retry-After` 只认秒数，遇到日期格式抛 `ValueError` 并把重试绕过去
- 已在线时劫持页是空响应，锐捷 `discover` 回退会拿到空 `queryString` 被服务端拒
- `unbind` 碰到传输错误会甩 200 字符 HTML 原文，深澜尤其难看

### 变更

- `probe` 权重按"哪家独有"重排，判定要过门槛并领先 10 分；采样补
  `/eportal/index.jsp`、`InterFace.do`，并跟随劫持跳转；四条探针并发，慢网不再按 4 倍超时等
- 适配层签名改用 `PortalLike` 协议，去掉满地的 `type: ignore`
- `cli.py` 拆成入口 + `commands.py`，593 行的单文件走到头了
- 假门户补 `--variant`，锐捷解绑/深澜 `info` 都会真校验
- 抽出 `transport.py`：cookie、TLS 放宽、UA、状态码都收在一处，`Portal` 与探针共用；
  测试改为注入假 transport，不再 patch `Portal.request`
- `status --json` 加 `any_online`（门户里任何人），`online` 仍表示“你自己在线”
- `commands.py` 拆成 `commands/` 包（auth / account / scan / admin / watch + 公用 `_common`），
  最大的模块 180 行

### 移除

- 死代码：`Portal.get`、`RejectedError`、`Config.fingerprint`、`probe.ELSEWHERE`

## 1.0.0

首个正式版本，也是第一个 PyPI 版本。

**范围**：只做 Dr.COM / eportal。锐捷、深澜在 0.10.0 移除，实现留在 git 历史里。

**破坏性**（相对 0.9.x）：`status` 需要填了 account 才有意义、会区分“你”与“别人”；
`probe` 对锐捷/深澜只说“暂不支持”；`install` 之前先校验配置；报错里的密码默认打码。

已发布到 PyPI（`pip install campus-auth`），发布走 tag 触发的可信发布流水线。

## 0.10.4

### 变更

- 报错里的 URL 默认把 `user_password` 打成 `ab…yz`（Dr.COM 的密文密钥就是同一个 URL 里的 IP，
  等于明文）；要看原文加 `--show-secrets`
- `urls` 命令补一句提示：快捷方式里的密文可还原，分享 `.url` 等于给出密码
- 免责段改成事实：列出密码实际会流经的位置

## 0.10.3

### 修复

- 安装路径含 `&`（Windows `.cmd`）、`%`（systemd unit）、`&`（launchd plist）时自启会静默失效：
  现在 `.cmd` 一律加引号并把 `%` 写成 `%%`，unit 把 `%` 写成 `%%`、带空格的参数加引号，
  plist 走 XML 转义
- CI 增加 `tools/check_install_artifacts.py`（三平台产物转义自检）与 `install --dry-run` 冒烟

## 0.10.2

### 修复

- 回的就是 HTML（改版、地址写错）时不再重复请求三次：解析失败改抛 `ParseError`，
  重试只留给真正的传输错误
- 4xx/5xx 一律算失败，不再因为错误页里带个 `{"result":0}` 就当成功
- `campus-auth ... | head` 不再吐 traceback、不再返回 120：管道断开与 Windows 的
  errno 22 都静默收尾并返回 0
- `check` 按错误类型退码（解析失败 1、传输失败 4），不再一律 3

## 0.10.0 —— 范围收敛到 Dr.COM

**破坏性**：锐捷、深澜整条线移除。维护者拿不到真机，不想一直挂着“未实机”。
两者已经做过的实现留在 git 历史里（最后一个含它们的版本是 `0.9.8`）。

### 移除

- `adapters/ruijie.py`、`adapters/srun.py`、`crypto_srun.py` 及其测试；
  `probe` 仍能认出这两家，判到就直说“暂不支持”
- 只有它们用到的基建：`state.py`（`userIndex` 缓存）、`after_logout` 钩子、
  `check_url` / `--check-url`、`logout_needs_password`
- 假门户的 `--style ruijie|srun|srun --variant`，现在只剩 `drcom` 和 `router`（路由器页）

### 变更

- `generic` 模板改成可继承的子类骨架；CONTRIBUTING 改成真实存在的 API
- 假门户会真解一遍账号密码（`wlan_user_ip` 推密钥、解不出来就拒）
- Issue 模板的门户类型可选锐捷/深澜并标注“暂不支持”

## 0.4.0

- 锐捷、深澜两条线（未实机）；`probe` 指纹判定；退出码契约；177 个测试

## 更早

见 `git log`。
