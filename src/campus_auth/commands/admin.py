"""管理面：init / adapters / urls / install / uninstall。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .. import adapters, credentials, net
from .. import install as installer
from ..config import ENV_PASSWORD, find_config_file
from ..errors import EXIT_CONFIG, EXIT_OK, CampusAuthError
from ..runner import _host_port, build
from ._common import CONFIG_TEMPLATE, _config, _err, _say


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.output or args.config or "campus-auth.toml")
    if target.exists() and not args.force:
        _err(f"{target} 已存在，加 --force 覆盖")
        return EXIT_CONFIG
    adapter = adapters.get_adapter(args.adapter or "huuc")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        CONFIG_TEMPLATE.format(
            env=ENV_PASSWORD,
            adapter=adapter.name,
            operators=" / ".join(adapter.operator_suffixes) or "（本适配层无）",
        ),
        encoding="utf-8",
    )
    _say(f"已写入 {target}")
    _say("下一步：填 account，然后存密码 —— `campus-auth password`（交互式，不回显）")
    if not credentials.available():
        _say(f"! 没装 keyring：改用 export ${ENV_PASSWORD}=...，或装 campus-auth[keyring]")
    _say("填完跑 `campus-auth status` 自检：没配好它会直接指出来")
    return EXIT_OK


def cmd_adapters(_: argparse.Namespace) -> int:
    for name in adapters.names():
        adapter = adapters.get_adapter(name)
        _say(f"{name:10} {adapter.school}  [{adapter.status}]  <{adapter.base_url}>")
        if adapter.notes:
            _say(f"{'':10} {adapter.notes}")
    return EXIT_OK


def cmd_urls(args: argparse.Namespace) -> int:
    config = _config(args)
    ctx = build(config, need_password=False)  # 不探活：配合 --ip 可以完全离线生成
    if not config.password:
        _say("! 没给密码，登录快捷方式里的密码字段会是空的")
    if not config.ip and not net.resolves(_host_port(ctx.portal.base_url)[0]):
        _say("! 门户域名解析不了，生成的 URL 要等你回到校园网才有效")

    # discover 要先敲一次门户，离线时可能拿不到
    discovered = True
    try:
        ctx.portal.prepare()
    except (CampusAuthError, ValueError) as exc:
        discovered = False
        _say(f"! 发现步骤没跑通（{exc}），只生成门户首页链接")

    targets: list[tuple[str, object]] = []
    if discovered:
        for operator in ["none", *ctx.adapter.operator_suffixes]:
            suffix = "" if operator == "none" else f"({operator})"
            ctx.portal.operator = operator
            targets.append((f"登录{suffix}", ctx.adapter.login_request(ctx.portal)))
        ctx.portal.operator = config.operator
        # 注销和解绑与运营商无关，各来一份就够
        targets.append(("注销", ctx.adapter.logout_request(ctx.portal)))
        targets.append(("解绑", ctx.adapter.unbind_request(ctx.portal)))
    else:
        targets.append(("门户首页", None))

    outdir = Path(args.output or "urls")
    outdir.mkdir(parents=True, exist_ok=True)
    post = False
    for name, request in targets:
        url = ctx.portal.base_url if request is None else ctx.portal.build_url(request)
        if request is not None and request.method.upper() != "GET":
            post = True
        (outdir / f"{name}.url").write_text(
            f"[InternetShortcut]\nURL={url}\n", encoding="ascii", newline="\n"
        )
        if os.name != "nt":
            (outdir / f"{name}.desktop").write_text(
                f"[Desktop Entry]\nType=Link\nName={name}\nURL={url}\n", encoding="utf-8"
            )
    _say(f"写入 {outdir}/: {', '.join(name for name, _ in targets)}")
    if post:
        _say(
            "! 该适配层用 POST 提交，快捷方式只带地址、没有表单体，"
            "点开会是错误页 —— 用 login 命令。"
        )
    _say("注意：URL 里绑着当前 IP 和一次性 challenge，换网段或过期就得重生成。")
    _say("! 快捷方式里的密码是密文，但密钥（IP）就在同一个 URL 里 —— 分享 .url 等于给出密码。")
    return EXIT_OK


def cmd_install(args: argparse.Namespace) -> int:
    config = _config(args)
    config.validate(need_password=False)  # 没账号装上也不会成功
    path = find_config_file(args.config)
    if path is None:
        _say("! 没找到配置文件：自启要一个真实路径，先 `campus-auth init` 或 --config 指一个")
        return EXIT_CONFIG

    service = installer.service_for(path)
    _say(f"要装的是: {service.kind} → {service.path}")
    if not config.password:
        _say("! 没读到密码：自启不继承当前 shell 的环境变量，先 `campus-auth password` 或写进配置")
    if args.dry_run:
        _say("")
        _say(service.content.rstrip())
        for argv in service.create:
            _say(f"$ {' '.join(argv)}")
        return EXIT_OK

    installer.check_python(sys.executable)
    installer.install(service)
    _say("已安装。")
    for note in service.notes:
        _say(f"· {note}")
    return EXIT_OK


def cmd_uninstall(args: argparse.Namespace) -> int:
    service = installer.service_for(find_config_file(args.config))
    if args.dry_run:
        _say(f"要卸的是: {service.kind} → {service.path}")
        for argv in service.remove:
            _say(f"$ {' '.join(argv)}")
        return EXIT_OK

    installer.uninstall(service)
    _say(f"已卸载（{service.path}）。")
    return EXIT_OK
