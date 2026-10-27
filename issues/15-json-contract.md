# `--json` 契约：已在线的 login 不出 JSON，人话还混在 stdout 里

- 级别：S4 · 成本：1 天 · 标签：`bug` `json` `P0`
- 落点：`src/campus_auth/commands/auth.py:105,113,127,138`（login）、`:94`（check）、`src/campus_auth/commands/scan.py:25-27`（probe 失败）、`src/campus_auth/cli.py:42-208`（父参数表）
- 契约出处：`docs/json.md:3-4`「`--json` 时 stdout 只有一个 JSON 对象……文案要么不出现、要么在 JSON 之前」
- 决策（Q2）：**稳定 API**。stdout 变纯，人话一律 stderr；不实现 `--json` 的六条命令**拒绝**该 flag

## 现象（均已实测）

1. **已在线的 `login --json` 一个 JSON 都不出**：`auth.py:108-110` 在 `_dump`（`:127`）之前就 `return EXIT_OK`，stdout 只有两行人话。
2. **JSON 前后都有人话**：`login --json` 实测 = 3 行人话 + JSON + `结果: 已在线`（`:138` 在 dump 之后）；`logout`/`unbind` 同理（`:155,179`）。
3. **`probe --json` 失败时 stdout 只有散文**：`scan.py:25-27` 把人话写进 stdout。
4. **`check --json` 忽略 flag**：`auth.py:94` 直接 `_say`。
5. **六个命令静默吃 flag**：`init`/`adapters`/`urls`/`password`/`install`/`uninstall` 接受 `--json` 后输出纯人话。

## 复现

```bash
python -m campus_auth login … --json | python -c "import json,sys; json.load(sys.stdin)"
# JSONDecodeError；已在线状态下整个文件为空
python -m campus_auth probe --url http://10.0.0.1:8080 --json   # stdout 无 JSON
python -m campus_auth check --json                              # 输出 "offline"
```

## 期望

- 新增 `_note(args, msg)`：`--json` 时 `_err`，否则 `_say`。所有面向人的输出改走它。
- 已在线不再提前 return：`_note` 提示后输出 `{"ok": true, "already_online": true, "result": true, "msg": "已经在线", "ret_code": 0, "hint": "", "ip": …}`。
- 其余 login 路径同样带 `"already_online": false`（additive）。
- `probe` 失败输出 `{"ok": false, "error": …}`，退出码用 `exc.exit_code`（transport 错 = 4）。
- `probe` 成功对象补 `"ok": true`，与错误对象对称，脚本可用 `jq -e .ok` 一把判。
- `check --json` 输出 `{"ok": <bool>, "online": <bool>}`。
- 六条命令撤掉 `--json`：拆出不含 `json` 的父参数（`plain` / `creds`），`campus-auth urls --json` 直接 argparse 报错、exit 2。

## 失败断言（先红后绿）

- `login --json` 的 stdout 首字符为 `{`、整段可 `json.loads`（成功 / 已在线 / 被拒三态各一条）。
- `logout`/`unbind`/`status`/`probe`/`watch` 同样；`probe` 失败可 `json.loads` 且 `ok is False`。
- `check --json` 可解析且含 `online`。
- 六条命令 `--json` → `SystemExit(2)`。
- `tests/test_json_schema.py` 的 `objects()` 宽松扫描换成「首字符断言 + 整段 loads」（watch 保留逐对象解码，但同样先断言首字符）。

## 验收

- 上述断言全绿；`--json` 时 `| jq -e .ok` 在七个命令上都能取到布尔。
- 无 `--json` 时的人读输出逐字不变（`git stash` 前后对比）。
- `docs/json.schema.json` 增 `check` 定义并纳入 `anyOf`；`login` 增 `already_online`；`docs/json.md` 写清支持清单与 stderr 约定。

## 边界

- 人话搬 stderr 后，`2>/dev/null` 的用户看不到提示 —— 在 CHANGELOG 与 `docs/json.md` 各写一句。
- 字段没变，只是流布局变化：**不升 `schema`**，在 CHANGELOG 标「1.4.0 破坏性」。
- `watch` 的 JSON 行为不动（已是逐事件对象）。
