# keyring 查询发生在命令行覆盖之前，`-a 学号` 反而拿不到密码

- 级别：S3 · 成本：半天 · 标签：`bug` `credentials`
- 落点：`src/campus_auth/config.py:163-167`（查钥匙串）与 `:169`（应用 overrides）

## 现象

`load()` 先用「文件里的 adapter/account」去查钥匙串，然后才应用命令行覆盖。于是：

- 配置里 `account` 为空、密码已在钥匙串里、用户 `login -a 0814`：
  `credentials.get(adapter, "")` 直接短路返回 `""`（`credentials.py:41` 空账号即返回），
  最终报「缺少必填项: password」—— 明明存着密码。
- 配置里写的是 A、用户 `login -a B`：静默用 **A 的密码**去登 B。这个更坏，因为不报错。

## 复现

```bash
CAMPUS_AUTH_CONFIG=/tmp/empty.toml python -m campus_auth login -a 0814 --url http://127.0.0.1:1
# 配置里没账号、钥匙串里有 huuc/0814 → 仍报「缺少必填项: password」
```

## 期望

先合并 overrides（至少 adapter/account），再决定要不要查钥匙串；钥匙串键必须与最终生效的身份一致。

## 失败断言

- 空账号配置 + 已存密码 + `-a 0814`（且未给 `-p`、未设环境变量）→ 不报缺密码。
- 配置 account=A、钥匙串只有 B 的密码、命令行 `-a B` → 用 B 的密码。
- 环境变量 `CAMPUS_AUTH_PASSWORD` 仍优先于钥匙串（既有顺序不许回退）。

## 验收

- 三条断言先红后绿；`tests/test_config.py` 增加「override 后重查」用例。
- 手工：`password -a X` 存一个，再 `login -a X` 不带 `-p`，确认能取到。

## 边界

- 配置文件的解析顺序（`--config` > env > `./` > 系统目录）不变。
- 只调整「何时查钥匙串」，不引入缓存。
