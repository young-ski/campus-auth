"""锐捷 ePortal（RG-SAM / `InterFace.do`）适配层。

跟 Dr.COM 完全是两套东西：

* 登录是 **POST 表单** 到 `/eportal/InterFace.do?method=login`
* 表单项 `userId` / `password` / `queryString` / `service`
* `queryString` 是门户劫持页 URL 里 `?` 之后那段，且 `&`、`=` 要**再编码一次**
  （`%2526` / `%253D`），服务端只解一层
* 注销、解绑也是同一个 `InterFace.do`，把 `method` 换成 `logout` / `unbind`
* 在线与否看 `generate_204` 是否返回 204，没有会话列表接口

门户地址靠 204 劫持页自己带出来，所以默认 `base_url` 是 204 的探测地址；
也可以直接 `--url http://门户/eportal/index.jsp?...` 省掉发现步骤。

状态：**未实机验证**。按公开脚本（callmeliwen/RuijiePortalLoginTool）的流程复刻，
各校锐捷版本有出入，跑不通请开 Issue 带打码样本。
"""

from __future__ import annotations

import re
import urllib.parse

from .. import state
from ..errors import ConfigError
from .base import Adapter, LoginResult, Param, Request

GENERATE_204 = "http://connect.rom.miui.com/generate_204"
INTERFACE_PATH = "/eportal/InterFace.do"
# 解绑用的 method 名。有的版本叫 unbind、有的在解绑页里另有写法，
# 服务端答「method 不对」时改这里（改完补一条测试）。
UNBIND_METHOD = "unbind"
_PORTAL_URL = re.compile(r"""location\.href\s*=\s*['"](https?://[^'"]+)['"]""", re.IGNORECASE)
_ANY_EPORTAL = re.compile(r"""https?://[^'"\s>]+/eportal/[^'"\s>]*""", re.IGNORECASE)

HINTS = {
    "用户已在线": "已经在线了，直接跑 status。",
    "账号或密码错误": "账号或密码不对；锐捷的账号就是学号，别加后缀。",
    "用户不存在": "账号不存在，确认是不是学号。",
    "IP已绑定": "这个 IP 绑了别的账号，先 unbind 或等绑定超时。",
    "终端数量达到上限": "同时在线的设备太多了，先注销别的。",
    "非法的用户组": "service 猜错了：用 --url 直接给完整的 index.jsp 地址。",
    "未登录": "手上没有可用的 userIndex：先在同一条命令里 login 一次，或缓存已经过期。",
}


class RuijieAdapter(Adapter):
    def __init__(self) -> None:
        super().__init__(
            name="ruijie",
            school="锐捷 ePortal（通用）",
            base_url=GENERATE_204,
            key_style="plain",
            status="未实机",
            notes="走 InterFace.do 的 POST 表单；靠 204 劫持页发现门户地址。",
        )

    # ---------- 发现 ----------

    def discover(self, portal, account: str) -> dict[str, object]:
        page = str(portal.base_url)
        if "/eportal/" not in page:  # 没给门户地址，先让 204 把我们指过去
            status, text = portal.raw(page)
            match = _PORTAL_URL.search(text) or _ANY_EPORTAL.search(text)
            if match:
                page = match.group(1) if match.re is _PORTAL_URL else match.group(0)
            elif "/eportal/" in text:
                page = portal.base_url  # 给的就是门户根，页面上有 eportal 路径
            else:
                # 已在线时劫持页会变成空 204，退回门户固定的 index.jsp 再试一次。
                # 劫持页 URL 里的 query 是必须的（登录/解绑都要），拿不到就照 IP 拼一个。
                origin = urllib.parse.urlsplit(portal.base_url)
                bare = f"{origin.scheme}://{origin.netloc}/eportal/index.jsp"
                page = ""
                for url in (f"{bare}?{urllib.parse.urlencode({'wlanuserip': portal.ip})}", bare):
                    got, body = portal.raw(url)
                    if got == 200 and "eportal" in body:
                        page = url
                        break
                if not page:
                    raise ConfigError(
                        f"从 {portal.base_url} 的劫持页里没找到门户地址（HTTP {status}）："
                        "用 --url 直接给 index.jsp 地址"
                    )

        split = urllib.parse.urlsplit(page)
        query = split.query
        login = urllib.parse.urlunsplit(
            (split.scheme, split.netloc, INTERFACE_PATH, "method=login", "")
        )
        unbind = urllib.parse.urlunsplit(
            (split.scheme, split.netloc, INTERFACE_PATH, f"method={UNBIND_METHOD}", "")
        )
        service = urllib.parse.parse_qs(query).get("service", [""])[0]
        return {
            "login_url": login,
            "unbind_url": unbind,
            "query_string": query.replace("&", "%2526").replace("=", "%253D"),
            "service": service,
            "referer": page,
        }

    # ---------- 登录 ----------

    def login_request(self, portal) -> Request:
        return Request(
            path=str(portal.ctx["login_url"]),
            method="POST",
            body={
                "userId": portal.account,
                "password": portal.password,
                "service": str(portal.ctx.get("service") or ""),
                "queryString": str(portal.ctx["query_string"]),
                "operatorPwd": "",
                "operatorUserId": "",
                "validcode": "",
                "passwordEncrypt": "false",
            },
            headers={
                "Referer": str(portal.ctx.get("referer") or ""),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

    def interpret_login(self, resp) -> LoginResult:
        message = str(resp.get("message") or resp.get("msg") or "")
        ok = str(resp.get("result") or "").lower() == "success"
        hint = "" if ok else self.hint_for(None, message)
        return LoginResult(ok=ok, msg=message, hint=hint)

    def hint_for(self, ret_code: int | None, msg: str) -> str:
        for needle, hint in HINTS.items():
            if needle in msg:
                return hint
        return f"服务端说: {msg or '(空)'}；接口行为参见 README 的「已知限制」。"

    def after_login(self, portal, payload) -> None:
        # 注销要靠 userIndex：本进程记着，同时落盘给下一次 logout 用（两条命令是两个进程）
        if payload.get("userIndex"):
            portal.ctx["user_index"] = str(payload["userIndex"])
            state.save_user_index(self.name, portal.account, portal.ip, str(payload["userIndex"]))

    def after_logout(self, portal, payload) -> None:
        # 注销成功了这份 userIndex 就作废，别留着下次去撞
        if str(payload.get("result") or "").lower() == "success":
            state.drop_user_index(self.name, portal.account, portal.ip)

    # ---------- 在线 / 会话 ----------

    def online_check(self, portal) -> bool | None:
        # 校园网常把 204 探测域名也拦掉，允许 --check-url 换一个
        url = getattr(portal, "check_url", "") or GENERATE_204
        status, _ = portal.raw(url, timeout=8)
        return status == 204

    def sessions_request(self, portal) -> Request:
        return Request(
            path=self._interface_url(portal, "getOnlineUserInfo"),
            params=[Param("method", "getOnlineUserInfo", encode=False)],
        )

    def interpret_sessions(self, payload):
        rows = payload.get("list") or payload.get("userInfo") or []
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    def logout_request(self, portal) -> Request:
        # 跟登录一样是 POST 表单：门户要的是 userIndex + queryString 的体。
        # 没在同一次进程里登录过就翻缓存（`logout` 和 `login` 是两条命令）
        index = str(portal.ctx.get("user_index") or "")
        if not index:
            index = state.load_user_index(self.name, portal.account, portal.ip)
        return Request(
            path=self._interface_url(portal, "logout"),
            method="POST",
            body={
                "userId": portal.account,
                "userIndex": index,
                "queryString": str(portal.ctx.get("query_string") or ""),
            },
            headers={"Referer": str(portal.ctx.get("referer") or "")},
        )

    def unbind_request(self, portal) -> Request:
        """解除 IP/MAC 绑定。

        跟注销同一条 `InterFace.do`，区别是带上学号 `userId`：
        注销只认 `userIndex`（拿不到就废），解绑靠账号本身，跨进程也能用。
        密码可选 —— 有的版本要它来证明是本人才让解绑，cmd_unbind 默认不给密码，
        配了 `-p` 才会带上。
        """
        body = {
            "userId": portal.account,
            "queryString": str(portal.ctx.get("query_string") or ""),
        }
        if portal.ctx.get("user_index"):
            body["userIndex"] = str(portal.ctx["user_index"])
        if getattr(portal, "password", ""):
            body["password"] = portal.password
        return Request(
            path=str(portal.ctx.get("unbind_url") or self._interface_url(portal, UNBIND_METHOD)),
            method="POST",
            body=body,
            headers={"Referer": str(portal.ctx.get("referer") or "")},
        )

    # ---------- 地址 ----------

    def _interface_url(self, portal, method: str) -> str:
        """把 `InterFace.do` 的地址换个 method；没走 discover 时按 base_url 推一个。"""
        login = str(portal.ctx.get("login_url") or "")
        if login:
            return login.replace("method=login", f"method={method}")
        origin = urllib.parse.urlsplit(str(portal.base_url))
        return urllib.parse.urlunsplit(
            (origin.scheme, origin.netloc, INTERFACE_PATH, f"method={method}", "")
        )


ADAPTER = RuijieAdapter()
