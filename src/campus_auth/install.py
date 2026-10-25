"""把 `watch` 装成登录自启的服务，以及卸掉它。

只生成当前平台认的东西，别的一律不做：

* Windows → 计划任务（`schtasks`，登录时启动）＋ 一个带日志重定向的 `.cmd` 包装
* Linux   → systemd **用户** unit（`Restart=always`，日志追加到 state 目录）
* macOS   → launchd LaunchAgent（`KeepAlive`，同上）

`--dry-run` 只打印将要写什么、跑什么。凭据不代管：计划任务不继承当前 shell 的环境变量，
密码请写进配置文件（或装 keyring 后由它取）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

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


def _watch_command(python: str, config_path: Path) -> list[str]:
    # -u：输出重定向进日志时要立刻落盘，别攒着
    return [python, "-u", "-m", "campus_auth", "watch", "--config", str(config_path)]


def _argv_line(command: Sequence[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def service_for(
    config_path: Path | None = None,
    *,
    python: str | None = None,
    platform: str | None = None,
) -> Service:
    """按平台拼出要装的东西；不认识的平台直接拒绝，别装一半。"""
    platform = platform or sys.platform
    python = python or sys.executable
    config_path = config_path or _config_home(platform) / "campus-auth.toml"
    command = _watch_command(python, config_path)

    if platform == "win32":
        return _windows(command, platform)
    if platform.startswith(("linux", "freebsd")):
        return _systemd(command, platform)
    if platform == "darwin":
        return _launchd(command, platform)
    raise ConfigError(f"还不认识 {platform} 的计划任务，照 `{_argv_line(command)}` 自己配一个")


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
            f'{_argv_line(command)} >> "{log}" 2>&1',
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
        f"ExecStart={_argv_line(command)}",
        "Environment=PYTHONIOENCODING=utf-8",
        "Restart=always",
        "RestartSec=30",
        f"StandardOutput=append:{log}",
        f"StandardError=append:{log}",
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
            f"日志在 {log}（`journalctl --user -u {SERVICE_NAME}` 也有）。",
        ],
    )


def _launchd(command: list[str], platform: str) -> Service:
    plist = Path.home() / "Library" / "LaunchAgents" / PLIST_NAME
    log = _state_home(platform) / "watch.log"
    args = "".join(f"\n        <string>{part}</string>" for part in command)
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
    <key>StandardOutPath</key><string>{log}</string>
    <key>StandardErrorPath</key><string>{log}</string>
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


def uninstall(service: Service, *, dry_run: bool = False, run: Runner = _default_runner) -> None:
    """先停后删；文件不在也不算错。"""
    if dry_run:
        return
    for argv in service.remove:
        run(argv)
    service.path.unlink(missing_ok=True)


__all__ = ["Service", "install", "service_for", "uninstall"]
