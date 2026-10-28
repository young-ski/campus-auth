# 加一所学校要改三处文件、手写测试，还没有「未验证」这个状态

- 级别：S3 · 成本：1 天 · 标签：`adapter` `dx` · 状态：已实现
- 落点：新增 `commands/new_adapter.py`、`cli.py`（子命令）、`adapters/base.py:100`（`status` 默认值）

## 现象

加适配层的真实门槛不是密钥算法，是流程：

1. 要知道抄 `example_generic.py`，还得知道抄到哪；
2. 抄完要手动改 `BUILTIN`；
3. 新适配层的 `status` **默认 `已验证`**（`base.py:100`），于是 `adapters` 一出生就说验证过了；
4. 没有骨架测试，跑不跑 `pytest` 全靠自觉。

外校学生照 CONTRIBUTING 走完 5 步，大概率卡在 1 与 2 之间。

## 期望

- `campus-auth new-adapter <代号>`：写一个可加载的子类骨架，含必改清单、`status="未验证"`，
  并直接打印 `--adapter ./x.py:ADAPTER` 的用法与登记位置。
- 代号做校验（`[a-z][a-z0-9_]*`），已存在要 `--force`。
- `Adapter.status` 默认改 `未验证`；`huuc`、`generic` 各自显式设置。
- CONTRIBUTING 第 1 步改成先跑脚手架。

## 失败断言

- 生成的文件能被 `get_adapter("<path>:ADAPTER")` 加载，`name` 等于代号、`status` 是 `未验证`。
- `new-adapter Foo`、`a-b` 报错（exit 2）。
- 重复生成不退 0；`--force` 可覆盖。
- 裸 `Adapter(...)` 的 `status` 是 `未验证`。
- 输出里含 `--adapter` 与 `BUILTIN`。

## 验收

- 五条断言先红后绿。
- 照输出从上到下走一遍，能到 `status`（假门户即可）。

## 边界

- 不做自动改 `BUILTIN`（用打印片段，避免命令行改源码）。
- 骨架只覆盖 Dr.COM 常见形态，锐捷/深澜仍靠手改。
