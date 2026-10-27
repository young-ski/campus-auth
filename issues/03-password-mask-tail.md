# 长密码的密文尾巴漏进 stderr 与 watch.log

- 级别：S4 · 成本：半天 · 标签：`bug` `security` `P0`
- 落点：`src/campus_auth/portal.py:27`（`_SECRET_PARAM`），使用处 `:37`

## 现象

```python
_SECRET_PARAM = re.compile(r"(user_password|password)=([^&\s]{1,80})")
```

正则只吃 80 个字符就停。Dr.COM 的密文是「每字符 2 位十六进制」，所以 45 字符的密码会编码成 90 位，**后 10 位原样留下**；打码结果还无缝拼接，看起来像密码本身坏了。

本机实测（对 500 页）：

```
user_password=40…404040404040
```

而按 `portal.py:31` 自己的注释，密钥就是同一 URL 里的 `wlan_user_ip` —— 拿到尾巴等于拿到部分明文。泄漏面覆盖 stderr、`watch.log` 及其 `.1` 备份（0644）。

## 复现

```bash
python -m campus_auth login -p "$(printf 'a%.0s' {1..45})" --url http://127.0.0.1:1
# 看错误行里的 user_password=
```

## 期望

`{1,80}` → `+`，任意长度都完整打码；顺带把 `≤4` 位全显的既有规则写进 docstring，避免下次又被当成 bug。

## 失败断言

- 45 字符密码：打码结果以「首 2 + `…` + 末 2」结尾，`len` 不随原值增长。
- 90 位以上密文同样不残留。
- 3 位/4 位短值维持现状（全显）。

## 验收

- 上述断言先红后绿；`tests/test_portal.py` 增加超长用例。
- 手工：对返回 500 的地址跑一次长密码 login，肉眼确认无尾巴。

## 边界

- 纯展示层，无协议影响。
- 短值全显是刻意设计（长度 ≤4 时打码反而更难核对），别顺手改掉。
