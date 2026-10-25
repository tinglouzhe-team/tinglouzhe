# -*- coding: utf-8 -*-
"""
PythonAnywhere 备用通道专用文件
================================
用法（详见教程第 12 章）：
1. 把整个项目文件夹放到 /home/你的用户名/tinglouzhe
2. PythonAnywhere 后台 Web 标签 → 选中你的 Web App → 点 WSGI configuration file 那一行
3. 把那个文件里的内容全删掉，把本文件的内容整段粘进去 → Save
4. 点 Web 标签上的 Reload

注意：PythonAnywhere 免费账号只能访问白名单里的外网，调用不了大模型接口，
所以这里只有"规则模式"（和本地不配 Key 时一模一样，功能完整、算得一样准）。
"""

import json
import os
import sys

# 项目文件夹：默认是 ~/tinglouzhe，如果你放到了别处，改这一行
PROJECT_DIR = os.path.expanduser("~/tinglouzhe")
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
os.chdir(PROJECT_DIR)

import agent          # noqa: E402
import engine         # noqa: E402

WEB_DIR = os.path.join(PROJECT_DIR, "web")

STATIC = {
    "/": "index.html",
    "/index.html": "index.html",
    "/static/style.css": "style.css",
    "/static/app.js": "app.js",
}
CTYPE = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


def _resp(start_response, code, body, ctype):
    data = body if isinstance(body, bytes) else body.encode("utf-8")
    start_response(code, [
        ("Content-Type", ctype),
        ("Content-Length", str(len(data))),
        ("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"),
        ("X-Content-Type-Options", "nosniff"),
    ])
    return [data]


def _json(start_response, obj, code="200 OK"):
    return _resp(start_response, code, json.dumps(obj, ensure_ascii=False),
                 "application/json; charset=utf-8")


def _read_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return {}
    raw = environ["wsgi.input"].read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET")

    if path == "/favicon.ico":
        return _resp(start_response, "204 No Content", b"", "image/x-icon")

    if method in ("GET", "HEAD") and path in STATIC:
        name = STATIC[path]
        full = os.path.join(WEB_DIR, name)
        if not os.path.exists(full):
            return _resp(start_response, "404 Not Found", f"缺少文件：{name}",
                         "text/plain; charset=utf-8")
        with open(full, "rb") as f:
            return _resp(start_response, "200 OK", f.read(), CTYPE[os.path.splitext(full)[1]])

    if method == "GET" and path == "/api/health":
        return _json(start_response, {
            "ok": True,
            "llm": agent.llm_available(),
            "mode": "llm" if agent.llm_available() else "rule",
            "port": "pythonanywhere",
            "pid": os.getpid(),
            "model": agent.LLM_MODEL or "",
        })

    if method == "GET" and path == "/api/network":
        return _json(start_response, {
            "zones": agent.NETWORK["zones"],
            "leaks": agent.NETWORK["leaks"],
            "gap": engine.zone_balance(agent.NETWORK["zones"]),
            "rank": engine.prioritize(agent.NETWORK["leaks"]),
        })

    if method == "POST":
        body = _read_body(environ)
        try:
            if path == "/api/decay":
                return _json(start_response, engine.decay_report(
                    float(body["v_m3"]), float(body["p1_bar"]),
                    float(body["p2_bar"]), float(body["t_min"]),
                    supply_flow=float(body["supply_flow"]) if body.get("supply_flow") else None,
                    specific_power=float(body.get("specific_power") or engine.DEFAULT_SP),
                    hours=float(body.get("hours") or engine.DEFAULT_HOURS),
                    price=float(body.get("price") or engine.DEFAULT_PRICE),
                ))
            if path == "/api/zones":
                return _json(start_response,
                             engine.zone_balance(body.get("zones") or agent.NETWORK["zones"]))
            if path == "/api/prioritize":
                return _json(start_response, engine.prioritize(
                    body.get("leaks") or agent.NETWORK["leaks"],
                    top_n=int(body.get("top_n") or 5),
                ))
            if path == "/api/potential":
                return _json(start_response, engine.saving_potential(
                    float(body["leak_flow"]), float(body["supply_flow"]),
                    target_rate=float(body.get("target_rate") or 0.10),
                ))
            if path == "/api/chat":
                msgs = body.get("messages") or []
                if not msgs and body.get("text"):
                    msgs = [{"role": "user", "content": body["text"]}]
                return _json(start_response, agent.chat(msgs))
        except KeyError as e:
            return _json(start_response, {"error": f"缺少字段 {e}"}, "400 Bad Request")
        except (TypeError, ValueError) as e:
            return _json(start_response, {"error": f"参数错误：{e}"}, "400 Bad Request")

    return _json(start_response, {"error": "not found"}, "404 Not Found")
