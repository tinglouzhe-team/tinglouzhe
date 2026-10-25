# -*- coding: utf-8 -*-
"""
一键体检：检查模型配置到底哪一步没生效
=====================================
用法（在那个黑窗口里）：
    python doctor.py

它会告诉你：
1. 三个环境变量有没有读到
2. 格式对不对（地址是不是以 /v1 结尾、Key 有没有多带空格）
3. 能不能真的连上模型（打印服务器原话，不翻译）
"""

import json
import os
import sys
import urllib.error
import urllib.request

OK = "[OK]"
BAD = "[!!]"
TIP = "     "


def mask(s: str) -> str:
    if not s:
        return "(空)"
    if len(s) <= 8:
        return s[0] + "*" * (len(s) - 1)
    return f"{s[:4]}...{s[-4:]}（共 {len(s)} 位）"


def main() -> int:
    base = os.environ.get("LLM_BASE_URL", "").strip()
    key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()

    print("=" * 60)
    print("  听漏者 · 模型配置体检")
    print("=" * 60)
    print(f"  LLM_BASE_URL = {base or '(空)'}")
    print(f"  LLM_API_KEY  = {mask(key)}")
    print(f"  LLM_MODEL    = {model or '(空)'}")
    print("-" * 60)

    problems = []

    if not base:
        problems.append("LLM_BASE_URL 没读到")
    elif not base.startswith("http"):
        problems.append("LLM_BASE_URL 不是以 http 开头")
    elif "/chat/completions" in base:
        problems.append("LLM_BASE_URL 只要填到 /v1（或 /v4）为止，后面那段程序会自己加")

    if not key:
        problems.append("LLM_API_KEY 没读到")
    elif key != key.strip() or " " in key:
        problems.append("LLM_API_KEY 里面带空格了，复制时多选了")
    elif len(key) < 16:
        problems.append(f"LLM_API_KEY 只有 {len(key)} 位，太短，可能没复制全")

    if not model:
        problems.append("LLM_MODEL 没读到")

    if problems:
        print(f"{BAD} 配置不完整，先解决下面这些：")
        for p in problems:
            print(f"     · {p}")
        print()
        print("  最常见原因：")
        print("     1) 你用的是 PowerShell，`set X=Y` 不生效——要用 $env:X=\"Y\"")
        print("     2) 三个 set 打在了一个窗口，python 在另一个窗口启动")
        print("     3) 设完没重启服务（环境变量只在启动那一刻读一次）")
        print()
        print("  最省事的做法：直接双击【启动_在线模式.bat】，它会挨个问你要三个值。")
        print("=" * 60)
        return 1

    print(f"{OK} 三个变量都在，格式看着正常，开始真连一次试试……")

    url = base.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "只回两个字：收到"}],
        "max_tokens": 16,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"{OK} 连上了！模型回话：{content!r}")
        print()
        print("  结论：配置完全正确。")
        print("  如果网页上还显示「本地规则模式」，那是浏览器缓存——按 Ctrl + F5 硬刷新。")
        print("=" * 60)
        return 0
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:400]
        print(f"{BAD} 服务器拒绝了，HTTP {e.code}")
        print(f"     原话：{detail}")
        print()
        hint = {
            401: "Key 不对或过期 → 回后台重新复制，注意别多带空格",
            403: "没有这个模型的权限 → 看后台是否要单独开通",
            404: "地址不对 → 检查结尾是不是 /v1，路径是不是 /chat/completions",
            429: "调用太频繁或额度用完 → 等一会儿再试",
        }.get(e.code, "看上面那段原话，整段复制给 AI 让它解释")
        print(f"     怎么办：{hint}")
        print("=" * 60)
        return 2
    except urllib.error.URLError as e:
        print(f"{BAD} 连不上：{e.reason}")
        print("     检查：网络是否正常、地址有没有写错、公司/学校网络是否拦截。")
        print("=" * 60)
        return 3
    except Exception as e:  # noqa: BLE001
        print(f"{BAD} 出了意外：{type(e).__name__}: {e}")
        print("=" * 60)
        return 4


if __name__ == "__main__":
    sys.exit(main())
