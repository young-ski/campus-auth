# 贡献指南

最需要的贡献只有一种：**你学校的适配层**。其次是错误码翻译和响应格式差异。

## 加一所学校

0. **先跑 `campus-auth probe --url <门户地址>`**。判成锐捷/深澜/没认出来就先别写适配层，
   方向不对会白写。判成 Dr.COM 再往下。
1. 复制 `src/campus_auth/adapters/example_generic.py` 成 `你的学校代号.py`（用小写拼音缩写，
   例如 `hncj`）。
2. 打开浏览器 F12 → Network，作为**普通用户**点一次登录，把真实请求抄下来。
   - 参数名不同 → 覆盖 `login_params()` / `logout_params()`
   - 值像 `%1a%2f...` 这样的十六进制 → `key_style = "ip-xor"`，
     并把密钥算法塞进 `encoder()`
   - 返回的不是 JSON → 覆盖 `interpret_login()`
3. 在 `adapters/__init__.py` 的 `BUILTIN` 里登记。
4. 跑 `pytest`，再跑一遍 `campus-auth status --adapter 你的代号` 做真机确认。
5. 提 PR，标题写 `adapter: <学校>`，正文附一段打码后的请求/响应样本。

**不要提交真实学号和密码。** 学校名和门户域名不算隐私，可以写。

## 约定

- 核心（`portal.py` / `cli.py` / `config.py`）里出现 `if adapter == "xx"` 就算错。
- 新的用户可见字符串写中文，代码注释也写中文，但标识符保持英文。
- 提交前 `ruff check . && ruff format . && pytest` 必须全绿（CI 会跑同一套）。
- 退出码是公开接口，改动要同步 README 的表。

## 报 bug

请附上：适配层名、Python 版本、`campus-auth --version`、退出码，
以及打码后的服务端原文。只说"登录不上"没法定位。

## 本地开发

```bash
python -m pip install -e '.[dev]'
pytest
```

改 `probe` 的指纹表时，用假门户做端到端确认，别只跑单测：

```bash
python tools/fake_portal.py --style ruijie --port 8765   # drcom / ruijie / srun
campus-auth probe --url http://127.0.0.1:8765
```

