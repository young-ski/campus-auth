# 安全策略

这个工具搬的是学号和密码，所以下面几条值得先看。

## 报告漏洞

用 GitHub 的私下通道：**Security → Advisories → Report a vulnerability**
（<https://github.com/young-ski/campus-auth/security/advisories/new>）。

不要在公开 issue 里贴真密码或真学号。已经泄露的凭据请自己先改掉再报告。

可以公开的信息：学校名、门户域名、`campus-auth --version`、退出码、打码后的报错原文。
`user_password=` 后面那段是密文而不是明文，但**密钥就是同一行里的 `wlan_user_ip`**，
所以贴整条登录 URL 跟贴明文差不多。

## 回应与修复

单人维护，尽力但不承诺 SLA：一般 3 天内给第一次回应。确认后会：

1. 在 advisories 里写清影响面与临时缓解；
2. 修复并发布补丁版本，CHANGELOG 里标注；
3. 需要时申请 CVE。

## 已知设计取舍（这些不算漏洞）

- **TLS 默认不校验证书**，`SECLEVEL` 降到 0：校园门户清一色自签，不少还停在 TLS 1.0 + SHA1。
  想校验加 `--verify-tls`。
- **`.url` / `.desktop` 里的密码等于明文**：密文的密钥是同 URL 的 IP，可离线还原。
- **`watch.log` 里也有密文**：权限随 umask（POSIX 通常 0644），并且不会自动清理。
- **密码会进 shell 历史**（用 `-p` 时）；`password` 子命令与 `--password-stdin` 不进。

## 凭据落在哪

内存、系统钥匙串（若启用）、配置文件（若写了）、`.url` 文件、报错与日志里的密文。
除此之外没有上传通道 —— 本工具不连任何中转服务器。
