#!/usr/bin/env python3
"""起一个假的 Dr.COM 门户，用来端到端验证 `probe` 的判定和 `login` 的实现。

    python tools/fake_portal.py                      # 假 Dr.COM 门户，8765
    python tools/fake_portal.py --style router       # 路由器页，探针应该判 unknown

    campus-auth probe --url http://127.0.0.1:8765
    campus-auth login --url http://127.0.0.1:8765 --ip 10.1.2.3 -a 20240001 -p pw

账号固定 `20240001`，密码 `pw`。服务端会真的用异或密钥解一遍 `user_account` /
`user_password` 再比对，所以 `login` 能过就说明编码没跑偏。
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from campus_auth.adapters.huuc import key_for
from campus_auth.crypto import xor_unhex

ACCOUNT, PASSWORD = "20240001", "pw"
IP = "10.1.2.3"
CHALLENGE_HOST = "127.0.0.1"

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

ROUTER_PAGE = """<!doctype html><html><head><title>路由器管理</title></head>
<body><p>TP-LINK 路由器</p><a href="/login.html">登录</a></body></html>"""

STATE = {"online": False}


class Handler(BaseHTTPRequestHandler):
    style = "drcom"
    client_ip = IP  # 发请求那台机器的 IP；客户端要 --ip 成一样，密钥才对得上

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

        if self.style == "router":
            return self._send(200, ROUTER_PAGE)

        if path in {"/generate_204", "/"}:
            if STATE["online"]:
                return self._send(204, "")
            target = (
                f"{CHALLENGE_HOST}:{self.server.server_port}"
                "/eportal/index.jsp?wlanuserip=10.1.2.3&service=x"
            )
            return self._send(200, f"<script>top.self.location.href='http://{target}'</script>")

        if path.endswith(".js"):
            return self._send(200, DRCOM_JS, "application/javascript")
        if path == "/eportal/index.jsp":
            return self._send(200, DRCOM_PAGE)

        if path == "/eportal/portal/online_list":
            rows = [{"online_ip": IP, "user_account": ACCOUNT}] if STATE["online"] else []
            return self._json({"result": 1, "ret_code": 0, "list": rows}, self._callback(query))

        if path == "/eportal/portal/login":
            # 密文在这里真解一遍。key 是"服务端看到的客户端 IP"，不是请求里那个
            # （请求里的 wlan_user_ip 自己也是密文），所以用 --client-ip
            key = key_for(self.client_ip)
            account = (query.get("user_account") or [""])[0]
            password = (query.get("user_password") or [""])[0]
            if xor_unhex(account, key) != f",0,{ACCOUNT}":
                return self._json({"result": 0, "ret_code": 1, "msg": "账号或密码错误"})
            if xor_unhex(password, key) != PASSWORD:
                return self._json({"result": 0, "ret_code": 1, "msg": "账号或密码错误"})
            STATE["online"] = True
            return self._json(
                {"result": 1, "ret_code": 0, "msg": "认证成功"}, self._callback(query)
            )

        if path == "/eportal/portal/logout":
            STATE["online"] = False
            return self._json({"result": 1, "ret_code": 0, "msg": "注销成功"})

        if path == "/eportal/portal/mac/unbind":
            return self._json({"result": 1, "ret_code": 0, "msg": "解绑成功"})

        return self._send(404, "not found")

    def log_message(self, *_args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--style", choices=["drcom", "router"], default="drcom")
    parser.add_argument("--client-ip", default=IP, help="当作客户端 IP，客户端要 --ip 成一样")
    args = parser.parse_args()
    Handler.style = args.style
    Handler.client_ip = args.client_ip
    print(f"假 {args.style} 起在 http://127.0.0.1:{args.port}")
    if args.style == "drcom":
        print(f"账号 {ACCOUNT} / {PASSWORD}，客户端 IP 当 {Handler.client_ip}")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
