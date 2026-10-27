# 文档化 `--adapter module:attr` 逃生舱，并建社区适配层目录

- 级别：S2 · 成本：半天 · 标签：`docs` `adapter`
- 落点：`README.md`（安装/加一所学校 两节）、`docs/schools.md`（新增）、`src/campus_auth/adapters/__init__.py:46`（已实现的逃生舱）
- 决策（Q3）：**先不引入 entry_points**。主仓 + 文档化逃生舱 + 手写目录，等「≥3 个外部适配层且 `Adapter` 连续两版无签名变化」再谈插件分发

## 现象

`--adapter` 已支持 `module:attr` 动态加载（`adapters/__init__.py:46-51`，`cli.py:63` 的 help 也写了「或 module:attr」），但 README 全篇只提「复制成 `<学校代号>.py`，再去 `adapters/__init__.py` 登记」—— 也就是说，README 只教了「fork 改主仓」这一条路。

外校用户于是要么改一份自己不需要维护的主仓，要么以为必须等 PR 合入。

## 期望

1. README「加一所学校」加一小节「不想改主仓 / 还没准备 PR」：给出 `campus-auth login --adapter ./my_school.py:ADAPTER` 的用法，说明模块只需暴露一个 `Adapter` 实例、`base_url` 可以留空由 `--url` 或配置给。
2. 同一小节写明三条边界：仍需本仓版本（`Adapter` 是内部 API）、升级时可能断、可用 `git+` 安装锁版本。
3. 新增 `docs/schools.md`：表格列为「学校 / 门户域名 / 适配层位置（本仓 / 外部链接）/ 状态（已验证 / 待验证）/ 维护者」，先放 huuc 与 generic 两行，并留一行「你的学校 → 提 issue」。
4. `adapters` 命令的输出末尾加一行指向该目录。

## 失败断言

- `grep -n "module:attr\|my_school.py" README.md` 有命中。
- `docs/schools.md` 存在，且表格含 `huuc` 与「待验证」字样。
- 用一个 tmp 目录里的最小适配层文件，按文档命令能加载成功（可做成 `tests/test_adapter.py` 用例：`get_adapter("<path>.py:ADAPTER")`）。

## 验收

- 三条断言先红后绿。
- 照文档从零写一个 `module:attr` 适配层，能跑到 `status`（可用 `tools/fake_portal.py` 验证，不必真机）。
- README 的既有 PR 路径不被删，两条路并列。

## 边界

- 不在本单引入 entry_points / 环境变量扫描。
- 外部模块的报错文案沿用现有 `ConfigError`（「导出适配层失败」），本单只补文档，不改加载器。
