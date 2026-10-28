## 改了什么

<!-- 一句话说清。加适配层就写学校代号；修 bug 就贴复现。 -->

## 为什么

<!-- 关联 issue 用 `Fixes #12`。 -->

## 自查

- [ ] `ruff check . && ruff format . && pytest` 全绿
- [ ] 没提交真实学号、密码、MAC
- [ ] 动了退出码或 `--json` 字段的话，同步了 `docs/json.md` 与 `docs/json.schema.json`
- [ ] 加了适配层：真机跑过 `status` 与一次 `login`，并在 `docs/schools.md` 记了一行
- [ ] 核心（`portal.py` / `commands/` / `config.py`）里没有出现 `if adapter == "xx"`

## 影响面

- [ ] 破坏性变更（参数、退出码、输出格式）
- [ ] 只影响文档 / 测试

## 备注

<!-- 打码后的请求/响应样本贴这里。 -->
