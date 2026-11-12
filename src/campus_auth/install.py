r"""把 `watch` 装成登录自启的服务，以及卸掉它。

只生成当前平台认的东西，别的一律不做：

* Windows → `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`（登录时拉起）＋ 一个循环重启的
  `.cmd` 包装（不走管理员，也不用 `schtasks`）
* Linux   → systemd **用户** unit（`Restart=always`，日志追加到 state 目录）
* macOS   → launchd LaunchAgent（`KeepAlive`，同上）

`--dry-run` 只打印将要写什么、跑什么。凭据不代管：计划任务不继承当前 shell 的环境变量，
密码请写进配置文件（或装 keyring 后由它取）。
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from .errors import ConfigError

TASK_NAME = "campus-auth-watch"
SERVICE_NAME = "campus-auth-watch.service"
PLIST_NAME = "cn.campus-auth.watch.plist"
RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"

Runner = Callable[[Sequence[str]], None]


@dataclass
class Service:
    """装一套服务要的全部材料。"""

    kind: str
    path: Path
    log_path: Path
    content: str
    create: list[list[str]] = field(default_factory=list)
    remove: list[list[str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _config_home(platform: str) -> Path:
    if platform == "win32":
        base = os.environ.get("APPDATA")
        return Path(base) / "campus-auth" if base else Path.home() / ".campus-auth"
    return _xdg_config_home() / "campus-auth"


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _systemd_user_dir() -> Path:
    """systemd 只认 `$XDG_CONFIG_HOME/systemd/user`，不能再往里套一层自己的目录。"""
    return _xdg_config_home() / "systemd" / "user"


def _state_home(platform: str) -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / "campus-auth"
    if platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return Path(local) / "campus-auth" if local else Path.home() / ".campus-auth"
    return Path.home() / ".local" / "state" / "campus-auth"


def running_pyz() -> Path | None:
    """如果当前进程就是单文件 pyz，返回它的路径。

    这种运行方式下 `python -m campus_auth` 是**不存在**的（包没装进 site-packages），
    自启必须改成 `python <这个文件> watch`，否则装完一跑就 import 失败。
    """
    if not sys.argv or not sys.argv[0]:
        return None
    candidate = Path(sys.argv[0])
    if candidate.suffix.lower() == ".pyz" and candidate.is_file():
        return candidate.resolve()
    return None


def _watch_command(
    python: str, config_path: Path, platform: str, pyz: Path | None = None
) -> list[str]:
    # -u：输出进日志时要立刻落盘；--log 自己按大小轮转，别靠 shell 的 >>
    entry = [str(pyz)] if pyz is not None else ["-m", "campus_auth"]
    return [
        python,
        "-u",
        *entry,
        "watch",
        "--config",
        str(config_path),
        "--log",
        str(_state_home(platform) / "watch.log"),
    ]


def _cmd_line(command: Sequence[str]) -> str:
    """cmd.exe 的命令行。

    一律加引号（`&`、`|`、`<`、`>`、空格在引号里就是字面量），`%` 在引号里仍会展开，
    所以还要写成 `%%`。
    """
    return " ".join(f'"{part.replace("%", "%%")}"' for part in command)


def _unit_line(command: Sequence[str]) -> str:
    r"""systemd 的 ExecStart。

    `%` 是 unit specifier，无论加不加引号都要写成 `%%`；含空格的参数用引号，
    引号内的 `\` 与 `"` 按 systemd 规则转义。
    """
    parts = []
    for part in command:
        part = part.replace("%", "%%")
        if " " in part or "	" in part:
            part = '"' + part.replace("\\", "\\\\").replace('"', '\\"') + '"'
        parts.append(part)
    return " ".join(parts)


def _xml(text: str) -> str:
    return escape(str(text))


def service_for(
    config_path: Path | None = None,
    *,
    python: str | None = None,
    platform: str | None = None,
    pyz: Path | None = None,
) -> Service:
    """按平台拼出要装的东西；不认识的平台直接拒绝，别装一半。"""
    platform = platform or sys.platform
    python = python or sys.executable
    config_path = config_path or _config_home(platform) / "campus-auth.toml"
    command = _watch_command(python, config_path, platform, pyz)

    if platform == "win32":
        return _windows(command, platform)
    if platform.startswith(("linux", "freebsd")):
        return _systemd(command, platform)
    if platform == "darwin":
        return _launchd(command, platform)
    raise ConfigError(f"还不认识 {platform} 的计划任务，照 `{_cmd_line(command)}` 自己配一个")


def _windows(command: list[str], platform: str) -> Service:
    """写 HKCU\\...\\Run：不用管理员，也不依赖写 Startup 文件夹（有的机器上被策略挡住）。"""
    shim = _config_home(platform) / f"{TASK_NAME}.cmd"
    log = _state_home(platform) / "watch.log"
    pythonw = Path(command[0]).with_name("pythonw.exe")
    if pythonw.is_file():
        command = [str(pythonw), *command[1:]]
    content = "\r\n".join(
        [
            "@echo off",
            "rem 由 `campus-auth install` 生成，改配置前先 uninstall",
            # Run 键只在登录时拉起一次，没有守护进程：崩了就等半分钟再来
            ":loop",
            _cmd_line(command),
            "ping -n 31 127.0.0.1 >nul",
            "goto loop",
            "",
        ]
    )
    return Service(
        kind="run-key",
        path=shim,
        log_path=log,
        content=content,
        create=[["reg", "add", RUN_KEY, "/v", TASK_NAME, "/t", "REG_SZ", "/d", str(shim), "/f"]],
        remove=[["reg", "delete", RUN_KEY, "/v", TASK_NAME, "/f"]],
        notes=[
            "已登记为登录自启（任务管理器的「启动」里能看到，随时可关）。",
            f"想现在就试，直接跑 {shim}。",
            f"日志在 {log}。",
        ],
    )


def _systemd(command: list[str], platform: str) -> Service:
    unit = _systemd_user_dir() / SERVICE_NAME
    log = _state_home(platform) / "watch.log"
    lines = [
        "[Unit]",
        "Description=campus-auth 校园网断线保活",
        "After=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"ExecStart={_unit_line(command)}",
        "Environment=PYTHONIOENCODING=utf-8",
        "Restart=always",
        "RestartSec=30",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ]
    return Service(
        kind="systemd",
        path=unit,
        log_path=log,
        content="\n".join(lines),
        create=[
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", SERVICE_NAME],
        ],
        remove=[
            ["systemctl", "--user", "disable", "--now", SERVICE_NAME],
            ["systemctl", "--user", "daemon-reload"],
        ],
        notes=[
            "只有登录着才跑；想登出后继续，跑一次 `loginctl enable-linger $USER`。",
            f"日志在 {log}（自己按大小轮转）。",
        ],
    )


def _launchd(command: list[str], platform: str) -> Service:
    plist = Path.home() / "Library" / "LaunchAgents" / PLIST_NAME
    log = _state_home(platform) / "watch.log"
    args = "".join(f"\n        <string>{_xml(str(part))}</string>" for part in command)
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>cn.campus-auth.watch</string>
    <key>ProgramArguments</key>
    <array>{args}
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
</dict>
</plist>
"""
    return Service(
        kind="launchd",
        path=plist,
        log_path=log,
        content=content,
        create=[["launchctl", "load", "-w", str(plist)]],
        remove=[["launchctl", "unload", "-w", str(plist)]],
        notes=[f"日志在 {log}。"],
    )


def _default_runner(argv: Sequence[str]) -> None:
    try:
        subprocess.run(argv, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ConfigError(f"找不到命令 {argv[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        raise ConfigError(
            f"{' '.join(argv)} 失败: {detail[-1] if detail else exc.returncode}"
        ) from exc


def install(service: Service, *, dry_run: bool = False, run: Runner = _default_runner) -> None:
    """写文件、跑安装命令。`dry_run` 只打印。"""
    if dry_run:
        return
    service.path.parent.mkdir(parents=True, exist_ok=True)
    service.path.write_text(service.content, encoding="utf-8")
    if os.name != "nt":
        service.path.chmod(0o644)
    service.log_path.parent.mkdir(parents=True, exist_ok=True)
    for argv in service.create:
        run(argv)


def adopt_pyz(pyz: Path, *, platform: str | None = None) -> Path:
    """把正在跑的 pyz 复制到配置目录，自启指这份副本。

    直接指解压出来的那份，同学一删文件夹自启就断；配置目录跟着用户走。
    """
    platform = platform or sys.platform
    dest = _config_home(platform) / "campus-auth.pyz"
    if pyz.resolve() == dest.resolve():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pyz, dest)
    return dest


def remove_adopted_pyz(*, platform: str | None = None) -> None:
    """卸载时一并删掉那份副本；不在也不算错。

    正被 watch 占用时删不掉 —— 那不是错误，提示一句就够，别抛 traceback。
    """
    target = _config_home(platform or sys.platform) / "campus-auth.pyz"
    with contextlib.suppress(OSError):
        target.unlink(missing_ok=True)


def check_python(python: str, run: Runner = _default_runner) -> None:
    """装之前先确认这个解释器能 import 到 campus_auth。

    自启跑的是装的时候那个 python；它要是系统 python 或 pyz，装完才发现跑不起来。
    """
    try:
        run([python, "-c", "import campus_auth"])
    except ConfigError as exc:
        raise ConfigError(
            f"{python} 里 import 不到 campus_auth：先 `pip install .` 或换它的 python 再装"
        ) from exc


def check_entry(python: str, pyz: Path | None = None, run: Runner = _default_runner) -> None:
    """装自启前的自检：pyz 就直接跑那个文件，别去 import 根本没装的包。

    从压缩包跑的时候 `python -m campus_auth` 必然失败（包不在 site-packages），
    以前会让人「先 pip install .」，而认证前根本连不上网。
    """
    if pyz is None:
        check_python(python, run)
        return
    try:
        run([python, str(pyz), "--version"])
    except ConfigError as exc:
        raise ConfigError(f"{python} 跑不了 {pyz}：{exc}") from exc


def uninstall(
    service: Service, *, dry_run: bool = False, run: Runner = _default_runner
) -> list[str]:
    """先停后删；本来就没装也算卸载成功。

    返回没能执行成功的命令说明（已经不在的东西不该让它退非零 —— 同学点两次卸载
    是常态）。
    """
    if dry_run:
        return []
    failures: list[str] = []
    for argv in service.remove:
        try:
            run(argv)
        except ConfigError as exc:
            failures.append(str(exc))
    with contextlib.suppress(OSError):
        # 被占用（watch 还没退）时别抛 traceback，删得掉就删
        service.path.unlink(missing_ok=True)
    return failures


__all__ = [
    "Service",
    "adopt_pyz",
    "check_entry",
    "check_python",
    "install",
    "remove_adopted_pyz",
    "running_pyz",
    "service_for",
    "uninstall",
]
