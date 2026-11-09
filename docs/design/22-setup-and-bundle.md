# 发给同学的东西：`setup` 与 Windows 压缩包

- 级别：S3 · 成本：3 天 · 标签：`dx` `windows` `release` · 已实现（1.7.4）
- 落点：`src/campus_auth/commands/setup.py`、`packaging/`、`tools/make_bundle.py`

## 现象

起点是「自己发给关系好的同学」：目标用户多数在 Windows、不装 Python，也不会照 README 走
七步。原来最快的路径是 `pip install` → `probe` → `init` → 手改 TOML → `password` → `status`，
中间还有两处会 exit 3 的死路（无 keyring、`--show-secrets` 位置）。

## 决定

1. 分发物是**一个 zip**，不是 pip：`install.cmd` + `校园说明` + `免责` + `pyz` + `SHA256SUMS`。
2. **`install.cmd` 里一个字中文都不放**。cmd.exe 按 OEM 代码页读批处理，UTF-8 的 `echo`
   在 cp936 上会乱码；中文全部由 `setup`（Python，控制台编码正确）和 `.txt` 输出。
3. 引导逻辑进 `setup` 而不是批处理：批处理只负责查解释器、核校验和、调用、递退出码。
4. `.txt` 写进包时加 BOM，旧记事本才认得出 UTF-8。

## 关键实现点

- `setup` 先讲风险再动手；密码优先钥匙串，进不去才写配置文件（并打码回显长度）。
- 校验用手里那个密码，**不回头查钥匙串** —— 刚写进去不一定立刻读得到（这是先红后绿的测试暴露的）。
- 配置落在用户目录而不是解压目录：删文件夹不影响自启；发现顺序与 `default_config_path()` 同源。
- 重跑 `--force` 沿用原学号、跳过编辑器，双击两次不会死在「已存在」。
- `install.cmd` 分支：无 Python 打开下载页和说明；校验不过 exit 4；setup 失败 exit 1，
  不再一律 Done。

## 失败断言（先红后绿，17 条）

空账号/带 `@cmcc` 后缀/非 ASCII 密码各有断言；钥匙串与配置文件两条落位路各有断言；
TOML 转义（`"` 与 `\`）有断言；`install.cmd` 纯 ASCII、CRLF、`if errorlevel` 递码、
无 pyz 时拒绝运行各有断言；包内清单与校验和一致、`.txt` 带 BOM 各一条。

## 顺带修掉的真 bug

`zipapp` 的 `main=` 生成的 `__main__.py` 只调 `main()`、不 `sys.exit`，**pyz 永远退 0**。
退出码是公开契约，单文件形态上却整个失效（计划任务、`check` 都靠它）。改成自己写入口，
`tests/test_release.py` 用 `probe --url nonsense` 断言必须退 2。

## 验收

- 真实 Windows 上解压 → 空账号必须失败退出（不是 Done）→ 填账号后跑通 → 中文不乱码。
- CI 新增 `bundle` 作业：Windows runner 上跑一遍，断言校验和跑到、空账号不算成功。

## 边界

- 仍然要机器上有 Python 3.11+；EXE 是下一档（PyInstaller 的误报与签名成本未验）。
- 压缩包 sha256 打在构建输出里，供发群时一起贴；不额外做签名。
- 只覆盖 Windows；POSIX 用户继续走 pip。
