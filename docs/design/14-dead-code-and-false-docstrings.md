# 死代码与假 docstring 清理（一批）

- 级别：S1 · 成本：半天 · 标签：`tech-debt` `good first issue`
- 落点：见下，逐条独立可改，可拆成多个 PR

## 清单

1. `portal.py:200` —— `request()` 循环末尾的 `raise TransportError(...)` 不可达：循环体内每条路径要么 `return`、要么 `raise`、要么 `continue`。删掉，或改成循环后断言。
2. `portal.py:272` `iter_retry_delays()` —— 运行时无人调用（实际退避是 `:181` 的内联线性实现），却被 `__all__` 导出、被 `tests/test_portal.py:306` 测试，等于在测一个死函数。二选一：接进 `request()`，或删函数 + 删测试。
3. `probe.py:249` docstring 写「顺带抓最多 3 个同源 JS」，实际 `MAX_JS = 1`（`:25`）且抓取跨源（`urljoin` 无同源校验，`:286-291`、`:297-298`）。改文案为「1 个 JS，可跨源」，或把 `MAX_JS` 提到 3。
4. `cli.py:1` docstring「各子命令的实现都在 `commands.py`」—— 早就是 `commands/` 包。改。
5. `tests/json_schema_check.py:3-4` docstring 说「不支持 …… oneOf」，实现里支持的是 `anyOf`（`:46-49`）而 `oneOf` 根本没有。改文案。
6. `CHANGELOG.md:106-137` 与 `:5-37` 三节（1.3.0 / 1.2.1 / 1.2.0）整块重复，`4f09b31` 把同一 hunk 打了两遍。删后者。

## 失败断言

- `python -m pytest` 与 `ruff check .` 全绿。
- `grep -n "commands.py" src/campus_auth/cli.py` 无命中。
- `grep -c "^## 1.3.0" CHANGELOG.md` == 1。
- 若删 `iter_retry_delays`，`grep -rn iter_retry_delays` 全库无命中（含测试）。

## 验收

- 上面四条命令结果符合预期。
- 逐条独立提交，标题 `chore:` 前缀；`CHANGELOG` 那条不单独发版。

## 边界

- 第 2 条若选择「接进去」，必须保持现有退避数值（1.5、3.0 …上限 60），否则会动到线上节奏，需另开验收。
- 不要顺手重排 `probe.py` 的权重表（见 #4 的独立单）。
