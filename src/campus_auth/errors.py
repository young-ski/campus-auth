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


class ParseError(CampusAuthError):
    """响应拿到了，但不是能解析的 JSON。不重试：重发一遍还是一样。"""

    exit_code = EXIT_REJECTED


class TransportError(CampusAuthError):
    exit_code = EXIT_TRANSPORT
