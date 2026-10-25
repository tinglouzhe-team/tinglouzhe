# -*- coding: utf-8 -*-
"""
听漏者 · Web 服务（公网版）
============================
零依赖：只用 Python 标准库。本地双击 run.bat 能跑，放到云端也能跑。

本地：
    python app.py
    浏览器打开 http://127.0.0.1:8000

云端（Render 等平台）会把 PORT 环境变量自动给你，代码直接读，不用改。

接口：
    GET  /                    页面
    GET  /api/network         示例管网与漏点数据
    GET  /api/health          健康检查（页面右上角"模式"就靠它）
    POST /api/decay           保压试验测算
    POST /api/zones           分区平衡
    POST /api/prioritize      修复优先级
    POST /api/potential       达标节电潜力
    POST /api/chat            智能体对话
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import agent
import engine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")


def _read_port() -> int:
    """云端平台（Render / Railway 等）会用环境变量 PORT 指定端口"""
    raw = os.environ.get("PORT", "").strip() or "8000"
    try:
        return int(raw)
    except ValueError:
        print(f"[提示] 环境变量 PORT 的值 {raw!r} 不是数字，改用 8000。", flush=True)
        return 8000


PORT = _read_port()

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    server_version = "TingLouZhe/1.1"
    protocol_version = "HTTP/1.1"      # 云端反向代理下更省连接；配合 Content-Length 不会卡

    # ------------------------------------------------------------ 工具方法
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # 禁止浏览器缓存：否则改了配置刷新还是旧页面，很容易误判
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code: int = 200):
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def log_message(self, fmt, *args):  # 安静一点；设了 VERBOSE=1 才打印每条请求
        if os.environ.get("VERBOSE"):
            super().log_message(fmt, *args)

    # ------------------------------------------------------------ 路由
    def do_OPTIONS(self):
        self._send(204, b"", "text/plain")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return

        if path in STATIC_FILES:
            name, ctype = STATIC_FILES[path]
            full = os.path.join(WEB_DIR, name)
            if not os.path.exists(full):
                self._send(404, f"缺少文件：{name}".encode("utf-8"), "text/plain; charset=utf-8")
                return
            with open(full, "rb") as f:
                self._send(200, f.read(), ctype)
            return

        if path == "/api/health":
            self._json({
                "ok": True,
                "llm": agent.llm_available(),
                "mode": "llm" if agent.llm_available() else "rule",
                # 下面三个用来区分"你看的到底是哪个进程"，排查"改了没生效"最有用
                "port": PORT,
                "pid": os.getpid(),
                "model": agent.LLM_MODEL or "",
            })
            return

        if path == "/api/network":
            zones = agent.NETWORK["zones"]
            leaks = agent.NETWORK["leaks"]
            self._json({
                "zones": zones,
                "leaks": leaks,
                "gap": engine.zone_balance(zones),
                "rank": engine.prioritize(leaks),
            })
            return

        self._send(404, b'{"error":"not found"}', "application/json; charset=utf-8")

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_json()
        try:
            if path == "/api/decay":
                self._json(engine.decay_report(
                    float(body["v_m3"]), float(body["p1_bar"]),
                    float(body["p2_bar"]), float(body["t_min"]),
                    supply_flow=float(body["supply_flow"]) if body.get("supply_flow") else None,
                    specific_power=float(body.get("specific_power") or engine.DEFAULT_SP),
                    hours=float(body.get("hours") or engine.DEFAULT_HOURS),
                    price=float(body.get("price") or engine.DEFAULT_PRICE),
                ))
                return

            if path == "/api/zones":
                self._json(engine.zone_balance(body.get("zones") or agent.NETWORK["zones"]))
                return

            if path == "/api/prioritize":
                self._json(engine.prioritize(
                    body.get("leaks") or agent.NETWORK["leaks"],
                    top_n=int(body.get("top_n") or 5),
                ))
                return

            if path == "/api/potential":
                self._json(engine.saving_potential(
                    float(body["leak_flow"]), float(body["supply_flow"]),
                    target_rate=float(body.get("target_rate") or 0.10),
                ))
                return

            if path == "/api/chat":
                msgs = body.get("messages") or []
                if not msgs and body.get("text"):
                    msgs = [{"role": "user", "content": body["text"]}]
                self._json(agent.chat(msgs))
                return

            self._json({"error": "not found"}, 404)
        except KeyError as e:
            self._json({"error": f"缺少字段 {e}"}, 400)
        except (TypeError, ValueError) as e:
            self._json({"error": f"参数错误：{e}"}, 400)


class Server(ThreadingHTTPServer):
    daemon_threads = True          # 关服务时不被卡住的连接拖住
    allow_reuse_address = True


def main():
    # 部署到云端必须监听 0.0.0.0，否则外面访问不到；本地打开地址仍是 127.0.0.1
    host = os.environ.get("HOST", "0.0.0.0")
    mode = "在线模型（已配置模型接口）" if agent.llm_available() else "规则引擎（未配置模型，离线可用）"

    try:
        srv = Server((host, PORT), Handler)
    except OSError as e:
        print("=" * 60, flush=True)
        print(f"  启动失败：{e}", flush=True)
        print(f"  最常见原因：端口 {PORT} 被别的程序占了。", flush=True)
        print("  本地解决办法：换个端口再启动，例如", flush=True)
        print("      Windows 命令提示符：  set PORT=8010 && python app.py", flush=True)
        print("      Windows PowerShell：  $env:PORT=8010 ; python app.py", flush=True)
        print("=" * 60, flush=True)
        return 1

    print("=" * 60, flush=True)
    print("  听漏者 · 压缩空气管网泄漏诊断智能体", flush=True)
    print(f"  本机打开：http://127.0.0.1:{PORT}", flush=True)
    print(f"  监听地址：{host}:{PORT}", flush=True)
    print(f"  进程号：{os.getpid()}   ← 和网页页脚对比，是同一个才算看对了", flush=True)
    print(f"  模式：{mode}", flush=True)
    print(f"  数据：{len(agent.NETWORK['zones'])} 个车间，"
          f"{len(agent.NETWORK['leaks'])} 个漏点", flush=True)
    print("  按 Ctrl+C 停止（关掉这个窗口，网页就打不开了）", flush=True)
    print("=" * 60, flush=True)

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。", flush=True)
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
