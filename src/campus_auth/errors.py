"""异常与退出码。

退出码是稳定接口，脚本和计划任务直接依赖它：

    0  成功
    1  认证失败 / 服务端拒绝
    2  配置问题（缺字段、适配层不存在）
    3  环境问题（不在校园网、取不到本机 IP）
    4  传输问题（超时、连接被拒、重试耗尽）
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_CONFIG = 2
EXIT_ENV = 3
EXIT_TRANSPORT = 4


class CampusAuthError(Exception):
    """本项目的所有异常的基类。"""

    exit_code = EXIT_REJECTED


class ConfigError(CampusAuthError):
    exit_code = EXIT_CONFIG


class EnvironmentError_(CampusAuthError):
    """取不到本机 IP、不在校园网等环境问题。"""

    exit_code = EXIT_ENV


class TransportError(CampusAuthError):
    exit_code = EXIT_TRANSPORT


class RejectedError(CampusAuthError):
    """服务端明确拒绝，携带 ret_code 与原始消息。"""

    exit_code = EXIT_REJECTED

    def __init__(self, message: str, ret_code: int | None = None) -> None:
        super().__init__(message)
        self.ret_code = ret_code
