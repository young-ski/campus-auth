"""`new-adapter`：生成一个能立刻加载的适配层骨架。

门槛不在密钥算法，在流程 —— 抄哪份、抄到哪、抄完怎么登记。这里把前两步变成一条命令，
生成的文件带「必改」清单和 `status="未验证"`，`adapters` 列表不会一出生就说验过了。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from ..errors import EXIT_CONFIG, EXIT_OK

NAME = re.compile(r"[a-z][a-z0-9_]*")

TEMPLATE = '''"""{school} 的 Dr.COM / eportal 适配层 —— 由 `campus-auth new-adapter {name}` 生成。

先跑 `campus-auth probe --url <门户地址>`，判成 Dr.COM 再往下改。

必改（其余留默认）：

1. `school` 与 `base_url`
2. 按 F12 抓到的真请求改参数名、`login_path` 一类的路径
3. `account_prefix` 与 `operator_suffixes`（门户不带前缀就把 account_prefix 改 ""）
4. 响应解读：`interpret_login()` / `hint_for()`，回的不是 JSON 就整个覆盖
5. 参数值是 `%xx` 十六进制时，`key_style` 改 "ip-xor"，密钥算法写进 `encoder()`

改完先验连通，再真机登录：

    campus-auth status --adapter ./{name}.py:ADAPTER --url <门户地址> -a <学号>
    campus-auth login  --adapter ./{name}.py:ADAPTER --url <门户地址> -a <学号>

最后把 `status` 改成 "已验证"，并在 `docs/schools.md` 记一行。
"""

from __future__ import annotations

from campus_auth.adapters.base import Adapter


class {klass}(Adapter):
    def __init__(self) -> None:
        super().__init__(
            name="{name}",
            school="TODO: 学校名",
            base_url="http://10.0.0.1:8080",  # TODO: 换成门户地址（要带 http(s)://）
            key_style="plain",  # 值是 %xx 十六进制就改 "ip-xor"
            account_prefix=",0,",  # 门户不带前缀就改 ""
            operator_suffixes={{}},  # 例如 {{"cmcc": "@cmcc"}}
            js_version="",  # Dr.COM 常见 4.2.1，别照抄
            status="未验证",
            notes="脚手架生成，尚未真机验证。",
        )


ADAPTER = {klass}()
'''


def _klass(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_")) + "Adapter"


def cmd_new_adapter(args: argparse.Namespace) -> int:
    name = args.name
    if not NAME.fullmatch(name):
        from ._common import _err

        _err(f"代号只能是小写字母、数字、下划线，且以字母开头：{name!r}")
        return EXIT_CONFIG

    if args.dir:
        out_dir = Path(args.dir)
    else:
        packaged = Path("src/campus_auth/adapters")
        out_dir = packaged if packaged.is_dir() else Path()
    target = out_dir / f"{name}.py"
    if target.exists() and not args.force:
        from ._common import _err

        _err(f"{target} 已存在，加 --force 覆盖")
        return EXIT_CONFIG

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        TEMPLATE.format(name=name, klass=_klass(name), school="TODO: 学校名"),
        encoding="utf-8",
    )

    from ._common import _say

    _say(f"已写入 {target}")
    _say("")
    _say("下一步：")
    _say("  1. 打开它，按「必改」清单改（school / base_url / 参数名 / 解读）")
    _say(
        f"  2. 先验连通：campus-auth status --adapter ./{name}.py:ADAPTER"
        " --url <门户地址> -a <学号>"
    )
    _say("  3. 真机登录一次，再把 status 改成 已验证")
    _say(
        f'  4. 要进主仓：把 "{name}": "campus_auth.adapters.{name}:ADAPTER" '
        "加进 src/campus_auth/adapters/__init__.py 的 BUILTIN"
    )
    return EXIT_OK


__all__ = ["cmd_new_adapter"]
