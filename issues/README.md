# 待提交 issue（2 周档）

16 个单子，覆盖二轮体检里所有 S1–S4 的运行时问题；外加 1 个文档单（Q3 决策）与 2 个发布链单（6 周档）。全部已在本机复现，行号对得上当前 HEAD（`4f09b31`）。

**已拍板**：Q1 = 门户为准（`01` 含兜底）、Q2 = `--json` 是稳定 API（`15` 含六条命令拒绝该 flag）、Q3 = 主仓 + 文档化逃生舱（`17`），`entry_points` 挂条件后置。

## 提交顺序

按批次建：第一批 4 条是「主承诺坏了」，先挂 `P0`；第二批是正确性；第三批是卫生。同批可并行。

| 批 | 文件 | 级别 | 成本 | 标签 |
|---|---|---|---|---|
| 1 | `01-watch-dns-shortcut.md` ✅ | S4 | 0.5d | `bug` `P0` |
| 1 | `02-pythonw-tee-none.md` ✅ | S4 | 0.5d | `bug` `P0` `windows` |
| 1 | `03-password-mask-tail.md` ✅ | S4 | 0.5d | `bug` `security` `P0` |
| 1 | `15-json-contract.md` ✅ | S4 | 1d | `bug` `json` `P0` |
| 2 | `04-probe-false-positive.md` ✅ | S2 | 0.5d | `bug` `probe` |
| 2 | `05-config-type-and-port.md` ✅ | S3 | 0.5d | `bug` `config` `good first issue` |
| 2 | `06-local-mac-substring.md` ✅ | S3 | 0.5d | `bug` `net` `windows` `good first issue` |
| 2 | `07-non-ascii-password.md` ✅ | S3 | 0.5d | `bug` `crypto` `good first issue` |
| 2 | `09-keyring-after-overrides.md` ✅ | S3 | 0.5d | `bug` `credentials` |
| 2 | `11-retry-scope-and-header-case.md` ✅ | S1 | 0.5d | `bug` `transport` `good first issue` |
| 3 | `08-mac-format-validation.md` ✅ | S2 | 0.5h | `bug` `config` `good first issue` |
| 3 | `10-two-watchers-one-log.md` ✅ | S3 | 0.5d | `bug` `logfile` |
| 3 | `12-verify-tls-bidirectional.md` ✅ | S2 | 0.5h | `dx` `tls` `good first issue` |
| 3 | `13-credentials-lie.md` ✅ | S2 | 0.5d | `bug` `credentials` |
| 3 | `14-dead-code-and-false-docstrings.md` ✅ | S1 | 0.5d | `tech-debt` `good first issue` |
| 3 | `16-probe-exit-code-split.md` ✅ | S3 | 0.5d | `bug` `probe` `dx` |
| 3 | `17-adapter-escape-hatch-docs.md` ✅ | S2 | 0.5d | `docs` `adapter` |
| 4 | `18-release-guard.md` ✅ | S2 | 1d | `ci` `release` |
| 4 | `19-zipapp-automation.md` ✅ | S2 | 1d | `ci` `release` |
| 4 | `20-new-adapter-scaffold.md` ✅ | S3 | 1d | `adapter` `dx` |

## 依赖关系

- `15` 与 `16` 共用 `scan.py` 的同一处 `except`：先合 `16`，再改 `15` 的 probe 分支，冲突最小。
- `01` 的最终形态已按 Q1 定稿（门户为准 + 连续 3 轮兜底）。
- `15` 已按 Q2 定稿（stdout 变纯、六条命令拒绝 flag、不升 `schema`）。
- `17` 按 Q3 定稿；`entry_points` 另开单，触发条件是「≥3 个外部适配层且 `Adapter` 连续两版无签名变化」。
- `05` 与 `16` 的「端口越界 → exit 2」是同一个验收点，合到 `05` 里实现，`16` 只引用。
- 其余互不依赖。

## 提交方式

```bash
gh label create P0 --description "主承诺损坏" --color B60205
gh label create probe --color 5319E7
# …按上表建完标签后逐条提交
gh issue create \
  --title "$(head -1 issues/01-watch-dns-shortcut.md | sed 's/^# //')" \
  --body-file issues/01-watch-dns-shortcut.md \
  --label bug,P0
```

标题取文件第一行去掉 `# `，正文原样。

## 状态

前两批 10 条已实现（✅）：`01`、`02`、`03`、`15`（第一批）与 `04`、`05`、`06`、`07`、`09`、`11`（第二批），各自都带了先红后绿的断言：第二批的 13 条断言先全红，修完全绿。当前 287 个测试与 `ruff check` / `ruff format --check` 全绿。

`17` 顺带把 `--adapter` 的文件路径加载补上了（`路径.py:ADAPTER`），不然文档里那条命令是假的。

全部条目提交时可直接用文件内容，标题按第一行取。

## 纪律

- 每个单子都写了「失败断言（先红后绿）」：先提交让断言变红的测试，再修，最后同 PR 合入。
- 没有红过的断言不算验收，评审时可以要求补 `git stash` 前后的对比。
- `14` 可拆成 6 个独立 PR，其余一单一 PR。

## 6 周档（无单独单子，已实现）

- C10 首成功路径：`probe` 自举发现门户、`init --url`、README 首屏外校分支
- C12 自启真跑：CI 在 Windows/macOS 真装真卸并用原生 shell 核实
- C13 `doctor`：一次摊开排障现场，密码只报来源
- C15 `SECURITY.md`、PR 模板、bug 模板补安装方式与 probe 输出
- C11 `new-adapter` 脚手架与「未验证」默认状态（单子见 `20-new-adapter-scaffold.md`）
- C19 第三方适配层包（entry point 组）、C20 学校目录收录标准与 README 英文首屏
- C14 日志时间戳带日期、C18 `probe --retries` 接线
- C17 只做了一半：`MAX_JS` 的假注释已改（issues/14）。追跳转**不限同源**是故意的 —— 真实门户常从网关 IP 跳到门户域名，限同源反而坏

## 暂不在这批

- `--show-secrets` 位置、README 事实修正、CHANGELOG 去重 → 已并入 `14` 或另批文档 PR。
- probe 跳转同源、登录确认轮询条件化、`--retries` 接线 → 6 周档。
- 首成功路径、new-adapter 脚手架、发布守卫 → 6 周档。
- 适配层 `entry_points` 分发 → Q3 后置项，条件见上。
