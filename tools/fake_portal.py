#!/usr/bin/env python3
"""起一个假门户，用来端到端验证 `campus-auth probe` 的判定。

python tools/fake_portal.py --style drcom  --port 8765
python tools/fake_portal.py --style ruijie --port 8765
campus-auth probe --url http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer

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

RUIJIE_JS = "function login(){var a=document.loginForm.userAccount.value}"  # noqa: E501

SRUN_PAGE = """<!doctype html><html><body><p>深澜认证系统</p>
<script src="/cgi-bin/srun_portal?action=challenge"></script>
<form action="/cgi-bin/srun_portal"><input name="srun_bx1"></form></body></html>"""

STYLES = {
    "drcom": (DRCOM_PAGE, DRCOM_JS),
    "ruijie": (RUIJIE_PAGE, RUIJIE_JS),
    "srun": (SRUN_PAGE, ""),
}


class Handler(BaseHTTPRequestHandler):
    style = "drcom"

    def do_GET(self) -> None:  # noqa: N802
        page, js = STYLES[self.style]
        if self.path.startswith("/eportal/portal/online_list") or "srun_portal" in self.path:
            will_jsonp = "callback=" in self.path
            cb = self.path.split("callback=")[1].split("&")[0] if will_jsonp else ""
            payload = '{"result":1,"ret_code":0,"list":[]}'
            body = f"{cb}({payload})" if will_jsonp else payload
            ctype = "application/javascript"
        elif self.path.endswith(".js"):
            body = js
            ctype = "application/javascript"
        else:
            body = page
            ctype = "text/html; charset=utf-8"
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Server", "nginx")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--style", choices=sorted(STYLES), default="drcom")
    args = parser.parse_args()
    Handler.style = args.style
    print(f"假 {args.style} 门户起在 http://127.0.0.1:{args.port}，Ctrl-C 结束")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
