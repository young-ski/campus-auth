#!/usr/bin/env python3
"""起一个假门户，用来端到端验证 `probe` 的判定和 `login` 的协议实现。

    python tools/fake_portal.py --style drcom  --port 8765
    python tools/fake_portal.py --style ruijie --port 8765
    python tools/fake_portal.py --style srun   --port 8765
    python tools/fake_portal.py --style srun --variant srun_bx2   # 另一代 info 编码

    campus-auth probe --url http://127.0.0.1:8765
    campus-auth login --adapter ruijie --url http://127.0.0.1:8765 -a 20240001 -p pw

账号固定 `20240001`，密码 `pw`。服务端会真的验一遍签名（深澜，按变体挑 base64
字母表）和表单（锐捷），所以 `login` 能过就说明客户端实现是对的。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from campus_auth.crypto_srun import SRUN_ALPHA, sha1_hex

ACCOUNT, PASSWORD = "20240001", "pw"
AC_ID, CHALLENGE = "12", "fakechallenge1234"
CHALLENGE_HOST = "127.0.0.1"
STD_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
# 变体 -> (info 前缀, 解码器)；跟适配层那边的 VARIANTS 一一对应
VARIANTS = {
    "srun_bx1": (
        "{SRBX1}",
        lambda text: base64.b64decode(
            text.translate(str.maketrans(SRUN_ALPHA, STD_ALPHA)), validate=True
        ),
    ),
    "srun_bx2": ("{SRBX2}", lambda text: base64.b64decode(text, validate=True)),
}

DRCOM_PAGE = """<!doctype html><html><head><title>Dr.COM 校园网登录</title>
<script src="/eportal/portal/js/a41.js"></script></head>
<body><form action="/eportal/portal/login">
<input name="wlan_user_ip"><input name="jsVersion" value="4.2.1">
<input type="hidden" name="encrypt" value="1"></form>
<p>城市热点 Dr.COM</p></body></html>"""

DRCOM_JS = """
function getkey(){var k=0;for(var i=0;i<ip.length;i++)k^=ip.charCodeAt(i);return k}
function enc_pwd(s,k){return s.split('').map(function(c){
  return ('0'+(c.charCodeAt(0)^k).toString(16)).slice(-2)}).join('')}
function load(){jsonp('dr1003', {})}
"""

RUIJIE_PAGE = """<!doctype html><html><head><title>锐捷上网登录</title>
<script src="/eportal/portal/js/index_1.js"></script></head>
<body><form action="/eportal/portal/login">
<input name="userAccount"><input name="userPassword" type="password"></form>
<p>RG-SAM 锐捷</p></body></html>"""

RUIJIE_JS = "function login(){var a=document.loginForm.userAccount.value}"

SRUN_PAGE = """<!doctype html><html><body><p>深澜认证系统</p>
<script>var ac_id='%(ac_id)s';var enc_ver='%(enc_ver)s';</script>
<form action="/cgi-bin/srun_portal"><input name="srun_bx1"></form></body></html>"""

STATE = {"online": False, "seq": 0, "user_index": ""}


class Handler(BaseHTTPRequestHandler):
    style = "drcom"
    variant = "srun_bx1"

    # ---------- 工具 ----------

    def _send(self, status: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Server", "nginx")
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, payload: dict, callback: str = "") -> None:
        body = json.dumps(payload, ensure_ascii=False)
        if callback:
            body = f"{callback}({body})"
        self._send(200, body, "application/javascript")

    def _callback(self, query: dict) -> str:
        return (query.get("callback") or [""])[0]

    # ---------- 路由 ----------

    def do_GET(self) -> None:  # noqa: N802
        split = urllib.parse.urlsplit(self.path)
        path, query = split.path, urllib.parse.parse_qs(split.query)

        if path == "/generate_204" or (path == "/" and self.style == "ruijie"):
            if STATE["online"]:
                return self._send(204, "")
            target = (
                f"{CHALLENGE_HOST}:{self.server.server_port}"
                "/eportal/index.jsp?wlanuserip=10.1.2.3&service=x"
            )
            return self._send(200, f"<script>top.self.location.href='http://{target}'</script>")

        if path == "/eportal/InterFace.do":
            # 注销有的版本走 GET，统一按 query 处理
            if query.get("method") == ["logout"]:
                STATE["online"] = False
                return self._json({"result": "success", "message": "注销成功"})
            return self._json({"result": "fail", "message": "method 不对"})

        if path in {"/eportal/index.jsp", "/eportal/redirectortosuccess.jsp"}:
            return self._send(200, RUIJIE_PAGE)
        if path.endswith(".js"):
            js = {"drcom": DRCOM_JS, "ruijie": RUIJIE_JS, "srun": ""}[self.style]
            return self._send(200, js, "application/javascript")
        if path == "/eportal/portal/online_list":
            rows = [{"online_ip": "10.1.2.3", "user_account": ACCOUNT}] if STATE["online"] else []
            return self._json({"result": 1, "ret_code": 0, "list": rows}, self._callback(query))

        if path == "/eportal/portal/login":
            # 密文不在这里解（客户端侧的异或有单测），只看必填项齐不齐
            if not query.get("user_account") or not query.get("user_password"):
                return self._json({"result": 0, "ret_code": 1, "msg": "参数不全"})
            STATE["online"] = True
            return self._json(
                {"result": 1, "ret_code": 0, "msg": "认证成功"}, self._callback(query)
            )
        if path == "/eportal/portal/logout":
            STATE["online"] = False
            return self._json({"result": 1, "ret_code": 0, "msg": "注销成功"})
        # Dr.COM 走这个通用路径；锐捷的解绑在 InterFace.do，深澜还没实现，
        # 所以后两者落到下面的 _serve_page，跟真门户一样回 HTML
        if path == "/eportal/portal/mac/unbind" and self.style == "drcom":
            return self._json({"result": 1, "ret_code": 0, "msg": "解绑成功"})

        if path == "/cgi-bin/get_challenge":
            return self._json(
                {"challenge": CHALLENGE, "client_ip": "10.1.2.3", "error": "ok"},
                self._callback(query),
            )
        if path == "/cgi-bin/rad_user_info":
            if STATE["online"]:
                return self._json(
                    {"error": "ok", "online_ip": "10.1.2.3", "user_name": ACCOUNT},
                    self._callback(query),
                )
            return self._json({"error": "not_online"}, self._callback(query))
        if path == "/cgi-bin/srun_portal":
            return self._srun(query)

        return self._serve_page()

    def _serve_page(self) -> None:
        if self.style == "srun":
            return self._send(200, SRUN_PAGE % {"ac_id": AC_ID, "enc_ver": Handler.variant})
        return self._send(200, {"drcom": DRCOM_PAGE, "ruijie": RUIJIE_PAGE}[self.style])

    def do_POST(self) -> None:  # noqa: N802
        split = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(split.query)
        length = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())

        if split.path == "/eportal/InterFace.do" and query.get("method") == ["login"]:
            if form.get("userId", [""])[0] != ACCOUNT or form.get("password", [""])[0] != PASSWORD:
                return self._json({"result": "fail", "message": "账号或密码错误"})
            if not form.get("queryString", [""])[0]:
                return self._json({"result": "fail", "message": "非法的用户组"})
            STATE["online"] = True
            STATE["seq"] += 1
            STATE["user_index"] = f"idx{STATE['seq']}"
            return self._json({"result": "success", "userIndex": STATE["user_index"]})
        if split.path == "/eportal/InterFace.do" and query.get("method") == ["logout"]:
            # 注销只认登录时发的 userIndex，靠开户进程里记着没用（两条命令两个进程）
            if form.get("userIndex", [""])[0] != STATE["user_index"]:
                return self._json({"result": "fail", "message": "未登录"})
            STATE["online"] = False
            return self._json({"result": "success", "message": "注销成功"})
        if split.path == "/eportal/InterFace.do" and query.get("method") == ["unbind"]:
            # 解绑不要求在线，但要学号证明解的是谁，queryString 缺了也不收
            if form.get("userId", [""])[0] != ACCOUNT:
                return self._json({"result": "fail", "message": "用户不存在"})
            if not form.get("queryString", [""])[0]:
                return self._json({"result": "fail", "message": "非法的用户组"})
            STATE["online"] = False
            return self._json({"result": "success", "message": "解绑成功"})
        return self._send(404, "not found")

    # ---------- 深澜 ----------

    def _srun(self, query: dict) -> None:
        action = (query.get("action") or [""])[0]
        callback = self._callback(query)

        if action == "logout":
            STATE["online"] = False
            return self._json({"error": "ok", "suc_msg": "注销成功"}, callback)

        user = (query.get("username") or [""])[0]
        info = (query.get("info") or [""])[0]
        prefix, decode = VARIANTS[Handler.variant]
        if user != ACCOUNT or not info.startswith(prefix):
            return self._json({"error": "login_error", "error_msg": "参数不全"}, callback)
        try:
            decode(info[len(prefix) :])
        except ValueError:
            return self._json(
                {"error": "login_error", "error_msg": "info 不是合法 base64"}, callback
            )

        md5 = hmac.new(CHALLENGE.encode(), PASSWORD.encode(), hashlib.md5).hexdigest()
        if (query.get("password") or [""])[0] != "{MD5}" + md5:
            return self._json({"error": "login_error", "error_msg": "密码错误"}, callback)

        fields = [user, md5, AC_ID, "10.1.2.3", "200", "1", info]
        expected = sha1_hex("".join(CHALLENGE + f for f in fields))
        if (query.get("chksum") or [""])[0] != expected:
            return self._json({"error": "login_error", "error_msg": "chksum 校验失败"}, callback)

        STATE["online"] = True
        return self._json({"error": "ok", "suc_msg": "认证成功"}, callback)

    def log_message(self, *_args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--style", choices=["drcom", "ruijie", "srun"], default="drcom")
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="srun_bx1")
    args = parser.parse_args()
    Handler.style = args.style
    Handler.variant = args.variant
    extra = f"，深澜变体 {args.variant}" if args.style == "srun" else ""
    print(f"假 {args.style} 门户起在 http://127.0.0.1:{args.port}{extra}")
    print(f"账号 {ACCOUNT} / {PASSWORD}")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
