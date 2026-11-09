# probe 的退出码与提示分裂：格式错退 3、传输错也退 3，提示永远怪「不在校园网」

- 级别：S3 · 成本：半天 · 标签：`bug` `probe` `dx`
- 落点：`src/campus_auth/commands/scan.py:23-27`、`src/campus_auth/probe.py:256`
- 契约出处：`README.md:93`「退出码：0 命中、1 未命中、**2 地址格式错**、3 探不到」，`errors.py` 也只有 3/4 两种对应关系

## 现象

`cmd_probe` 用一个 `except CampusAuthError` 把所有失败收成同一个出口：

```python
_err(str(exc))
_say("")
_say("提示：探针只从校园网内有效，先连学校 Wi-Fi 再试。")
return EXIT_ENV
```

于是：

- 地址写错 → `看不懂的地址: 'nonsense'` + **「先连学校 Wi-Fi」**（人明明可能就在校园网里），退出码 3 而文档写 2。
- 传输错误（`TransportError`，文档里是 4）→ 同样退 3。
- 格式问题与网络问题在脚本侧不可区分。

本机实测：`probe --url nonsense` → exit 3；`probe --url http://10.0.0.1:8080` → exit 3。

## 期望

- 按异常类型分流：`ConfigError`/地址解析失败 → 2 + 「地址格式」文案；`EnvironmentError_`（本机 IP 拿不到）→ 3；`TransportError` → 4。
- 提示语随之分流：只有 3/4 才说「先连校园网」，2 只说地址该怎么写。
- `probe.py:256` 改抛 `ConfigError`（「看不懂的地址」本来就是配置问题）。

## 失败断言

- `--url nonsense` → exit 2，stderr 含「地址」，stdout 不含「校园网」。
- `--url http://10.0.0.1:8080 --timeout 1` → exit 4，含「校园网」。
- 端口越界（`http://h:99999`）→ exit 2（与 #5 合并验收）。
- 命中/未命中仍为 0/1。

## 验收

- 四条断言先红后绿；`tests/test_probe.py` 的 `test_probe_offline` 拆分。
- README 退出码表核对一遍：表格值不许改，改代码去对表。

## 边界

- `check` 的同类问题（`auth.py:90-91` 直接 `return exc.exit_code` 尚可）不在本单。
- probe 的 `--json` 失败形态归 #15，两单共用同一处 except。
