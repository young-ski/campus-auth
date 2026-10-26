# 贡献指南

最需要的贡献只有一种：**你学校的 Dr.COM 适配层**。其次是错误码翻译和响应格式差异。

**本项目只做 Dr.COM / eportal。** 锐捷、深澜不在范围内 —— 它们的适配层已经被移除过一次，
别按老文档写。

## 加一所学校

0. **先跑 `campus-auth probe --url <门户地址>`**。判成 Dr.COM 再往下；判成别的说明不在范围。
1. 复制 `src/campus_auth/adapters/example_generic.py` 成 `你的学校代号.py`（小写拼音缩写，
   例如 `hncj`）。它是**可继承的子类骨架**，按注释覆盖方法，别改 core。
2. 打开浏览器 F12 → Network，作为**普通用户**点一次登录，把真实请求抄下来。
   - 参数名不同 → 覆盖 `account_params()` / `identity_params()`，或整个 `login_request()`
   - 值像 `%1a%2f...` 这样的十六进制 → `key_style = "ip-xor"`，把密钥算法写进 `encoder()`
   - 返回的不是 JSON → 覆盖 `interpret_login()` 和 `hint_for()`
3. 在 `adapters/__init__.py` 的 `BUILTIN` 里登记。
4. 跑 `pytest`，再跑一遍 `campus-auth status --adapter 你的代号` 做真机确认。
5. 提 PR，标题写 `adapter: <学校>`，正文附一段打码后的请求/响应样本。

**不要提交真实学号和密码。** 学校名和门户域名不算隐私，可以写。

## 约定

- 核心（`portal.py` / `transport.py` / `commands/` / `config.py`）里出现 `if adapter == "xx"` 就算错。
- 新的用户可见字符串写中文，代码注释也写中文，但标识符保持英文。
- 提交前 `ruff check . && ruff format . && pytest` 必须全绿（CI 会跑同一套）。
- 退出码和 `--json` 字段都是公开接口：改字段要同步 `docs/json.md` 与 `docs/json.schema.json`（`tests/test_json_schema.py` 会拿真实输出校验），破坏性改动把 `schema` 加一。

## 发布（维护者）

只走 tag：`pyproject.toml` 的版本和 tag 必须一致（workflow 会校验），push tag 后
`publish.yml` 自动 build、`twine check`、用 PyPI 可信发布上传，不需要 token。

首次需要有人在 PyPI 注册可信发布者：

- Owner `young-ski`、Repository `campus-auth`、Workflow `publish.yml`、Environment `pypi`

没注册之前 publish 作业会在上传一步失败（build 与检查仍然会过），把流水线里的
troubleshooting 链接给管理员看即可。

```bash
# 1. 改 pyproject 与 __init__ 的版本  2. 写 CHANGELOG
git commit -am "chore: x.y.z"
git push
gh release create vx.y.z dist/campus-auth.pyz --title vx.y.z --notes "…"
```

## 报 bug

请附上：适配层名、Python 版本、`campus-auth --version`、退出码、`campus-auth probe --json`
的输出，以及打码后的服务端原文。只说“登录不上”没法定位。

## 本地开发

```bash
python -m pip install -e '.[dev]'
pytest
```

改 `probe` 的指纹表时，用假门户做端到端确认，别只跑单测：

```bash
python tools/fake_portal.py                      # 假 Dr.COM 门户，账号 20240001 / 密码 pw
campus-auth probe --url http://127.0.0.1:8765
campus-auth login --url http://127.0.0.1:8765 --ip 10.1.2.3 -a 20240001 -p pw
```

假门户会用 `wlan_user_ip` 推出密钥、真解一遍账号和密码再比对 ——
编码跑偏（大小写、漏字段、少解一层）都会被打回，所以 `login` 过得了就说明实现是对的。

测试一律不碰网络，全部 monkeypatch；提交前请确认在断网机器上 `pytest` 也是绿的。
