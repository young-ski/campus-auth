# 变更记录

只记对本仓库使用者有影响的东西。版本号跟 `pyproject.toml` 走，日期在打 tag 时补。

## 未发布

### 变更

- 抽出 `transport.py`：cookie、TLS 放宽、UA、状态码都收在一处，`Portal` 与探针共用；
  测试改为注入假 transport，不再 patch `Portal.request`
- `status --json` 加 `any_online`（门户里任何人），`online` 仍表示“你自己在线”

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

## 未发布（0.5.0 → 0.9.8）

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

### 移除

- 死代码：`Portal.get`、`RejectedError`、`Config.fingerprint`、`probe.ELSEWHERE`

## 0.4.0

- 锐捷、深澜两条线（未实机）；`probe` 指纹判定；退出码契约；177 个测试

## 更早

见 `git log`。
