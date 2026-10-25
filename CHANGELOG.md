# 变更记录

只记对本仓库使用者有影响的东西。版本号跟 `pyproject.toml` 走，日期在打 tag 时补。

## 未发布（0.5.0 → 0.9.5）

### 新增

- `install` / `uninstall`：把 `watch` 装成登录自启（Windows `HKCU\...\Run` + `.cmd`，
  Linux `systemd --user`，macOS LaunchAgent），`--dry-run` 只打印；三条实现都带自动重启
- `watch --log`：自己写日志并按 1 MiB 轮转，留一份 `.1`
- 可选 `keyring`：`password` 命令存取、`login --remember` 顺手存；
  密码解析顺序变成 `$CAMPUS_AUTH_PASSWORD` > 配置文件 > 钥匙串
- 深澜 `srun_bx2` 变体：按页面里的 `enc_ver` 自动切换 `{SRBX2}` + 标准 base64
- 锐捷解绑：`InterFace.do?method=unbind`，`userIndex` 落盘 12 小时支撑跨进程注销

### 修复

- systemd unit 写到了 `systemctl` 不认的目录（`~/.config/campus-auth/systemd/user`）
- `Retry-After` 只认秒数，遇到日期格式抛 `ValueError` 并把重试绕过去
- 已在线时劫持页是空响应，锐捷 `discover` 回退会拿到空 `queryString` 被服务端拒
- `unbind` 碰到传输错误会甩 200 字符 HTML 原文，深澜尤其难看

### 变更

- `probe` 权重按"哪家独有"重排，判定要过门槛并领先 10 分；采样补
  `/eportal/index.jsp`、`InterFace.do`，并跟随劫持跳转
- 适配层签名改用 `PortalLike` 协议，去掉满地的 `type: ignore`
- 假门户补 `--variant`，锐捷解绑/深澜 `info` 都会真校验

### 移除

- 死代码：`Portal.get`、`RejectedError`、`Config.fingerprint`、`probe.ELSEWHERE`

## 0.4.0

- 锐捷、深澜两条线（未实机）；`probe` 指纹判定；退出码契约；177 个测试

## 更早

见 `git log`。
