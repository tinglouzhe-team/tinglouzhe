# -*- coding: utf-8 -*-
"""
听漏者 · 智能体层
==================
两条通路：
1. LLM 通路：调用任意 OpenAI 兼容接口（JoyCode 自带的模型即可），走标准 function calling；
2. 兜底通路：没配 API Key 时，用规则引擎跑同一批工具函数——保证断网也能演示。

两条通路调用的是同一组工具，所以"能力"完全一致，只是"听懂"的方式不同。
答辩时这句话很好用：模型负责听懂，代码负责算数。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

import engine

# ------------------------------------------------------------------ 配置
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")

DEFAULT_ZONES = [
    {"name": "1号车间", "header_flow": 18.5, "branches": [6.1, 5.4, 4.8]},
    {"name": "2号车间", "header_flow": 15.2, "branches": [5.2, 5.0, 4.6]},
    {"name": "3号车间", "header_flow": 16.8, "branches": [4.0, 3.6, 3.2]},
]

DEFAULT_LEAKS = [
    {"location": "3号车间-东侧法兰", "flow": 0.42, "cost": 800},
    {"location": "3号车间-快换接头×6", "flow": 0.35, "cost": 600},
    {"location": "2号车间-气动三联件排水阀", "flow": 0.28, "cost": 300},
    {"location": "1号车间-软管接头×4", "flow": 0.18, "cost": 400},
    {"location": "主管道-焊口砂眼", "flow": 0.55, "cost": 3200},
    {"location": "2号车间-备用支管盲板", "flow": 0.12, "cost": 200},
]


def _load_network() -> dict:
    """优先读 data/network.json；读不到就用内置默认值，保证永远不会启动失败"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "network.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {
            "zones": data.get("zones") or DEFAULT_ZONES,
            "leaks": data.get("leaks") or DEFAULT_LEAKS,
            "system": data.get("system") or {},
        }
    except (OSError, json.JSONDecodeError):
        return {"zones": DEFAULT_ZONES, "leaks": DEFAULT_LEAKS, "system": {}}


NETWORK = _load_network()

SYSTEM_PROMPT = """你是"听漏者"，压缩空气管网泄漏诊断与修复决策助手。

# 服务对象
工厂设备管理员、能源管理员。他们知道"气在漏"，但说不清漏了多少、漏在哪个区、先修哪个。

# 六步工作流程（不得跳步）
1. 信息核对：保压试验需要 容积V(m3)、起始压力P1(bar)、终止压力P2(bar)、压降时间t(min)，
   以及可选的总产气量、比功率、年运行小时、电价。缺项先用一次提问列清楚，不要猜。
2. 计算：调用工具算泄漏量，公式 Q = V×(P1−P2)/(t×1.013)。
3. 判级：按泄漏率给出优/良/差/极差。
4. 定位：调用分区平衡工具，指出差额最大的区段。
5. 排序：调用优先级工具，按回收期给出"先修哪几个"。
6. 输出：结论、数据核对、计算过程、定位、清单、下一步。

# 输出格式
【结论】一句话
【数据核对】用到的参数，缺失项标"需现场提供"
【计算过程】公式 + 代入 + 结果
【问题定位】区段 + 证据
【修复清单】表格：位置｜泄漏量｜投资｜年省｜回收期
【下一步】2-3 条

# 铁律
1. 不得编造任何容积、压力、比功率、修复价格。没有就说"需现场提供"。
2. 用户说"关小总阀""降低压力"来治泄漏时，必须纠正：关小阀门是增加阻力，不是节能；
   降压力确实能省电（约 7%/bar），但泄漏本身没有消失，且可能让末端设备出力不足。
3. 泄漏率超过 40% 或泄漏量超过 10 m3/min 时，先提示数据可疑，要求复核。
4. 所有金额必须说明假设：年运行小时、电价、比功率。
5. 维修投资给区间，注明"按同类项目估算"，不得承诺精确收益。
6. 与压缩空气无关的问题，一句话转介，不展开。

# 语言
工程师口吻，短句，先结论后过程，数字带单位。每次回答不超过 350 字（清单除外）。
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "decay_test",
            "description": "保压（压降）试验测算：由容积、压降、时间算泄漏量与年损失",
            "parameters": {
                "type": "object",
                "properties": {
                    "v_m3": {"type": "number", "description": "储气罐+管路总容积 m3"},
                    "p1_bar": {"type": "number", "description": "起始压力 bar"},
                    "p2_bar": {"type": "number", "description": "终止压力 bar"},
                    "t_min": {"type": "number", "description": "压降时间 min"},
                    "supply_flow": {"type": "number", "description": "空压机总产气量 m3/min，可选"},
                    "specific_power": {"type": "number", "description": "比功率 kWh/m3，默认0.12"},
                    "hours": {"type": "number", "description": "年运行小时，默认6000"},
                    "price": {"type": "number", "description": "电价 元/kWh，默认0.65"},
                },
                "required": ["v_m3", "p1_bar", "p2_bar", "t_min"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "zone_balance",
            "description": "分区流量平衡，定位泄漏最严重的区段",
            "parameters": {
                "type": "object",
                "properties": {
                    "zones": {
                        "type": "array",
                        "description": "分区列表，每项含 name、header_flow、branches 数组",
                        "items": {"type": "object"},
                    }
                },
                "required": ["zones"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prioritize_repairs",
            "description": "按静态回收期对漏点排序，给出先修哪几个",
            "parameters": {
                "type": "object",
                "properties": {
                    "leaks": {
                        "type": "array",
                        "description": "漏点列表，每项含 location、flow(m3/min)、cost(元)",
                        "items": {"type": "object"},
                    },
                    "top_n": {"type": "number", "description": "取前几个，默认5"},
                },
                "required": ["leaks"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "saving_potential",
            "description": "把泄漏率降到目标值可节省的年电量与费用",
            "parameters": {
                "type": "object",
                "properties": {
                    "leak_flow": {"type": "number", "description": "当前泄漏量 m3/min"},
                    "supply_flow": {"type": "number", "description": "总产气量 m3/min"},
                    "target_rate": {"type": "number", "description": "目标泄漏率，默认0.10"},
                },
                "required": ["leak_flow", "supply_flow"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pressure_reduction",
            "description": "评估降低供气压力的节电潜力（用于回应'关小总阀'类问题）",
            "parameters": {
                "type": "object",
                "properties": {
                    "p_now": {"type": "number", "description": "当前供气压力 bar"},
                    "p_target": {"type": "number", "description": "目标压力 bar"},
                    "total_flow": {"type": "number", "description": "系统总用气量 m3/min"},
                },
                "required": ["p_now", "p_target", "total_flow"],
            },
        },
    },
]


def execute_tool(name: str, args: dict) -> dict:
    """工具执行器：所有计算都从这里走，模型不参与算数"""
    try:
        if name == "decay_test":
            return engine.decay_report(
                float(args["v_m3"]), float(args["p1_bar"]),
                float(args["p2_bar"]), float(args["t_min"]),
                supply_flow=float(args["supply_flow"]) if args.get("supply_flow") else None,
                specific_power=float(args.get("specific_power") or engine.DEFAULT_SP),
                hours=float(args.get("hours") or engine.DEFAULT_HOURS),
                price=float(args.get("price") or engine.DEFAULT_PRICE),
            )
        if name == "zone_balance":
            return engine.zone_balance(args.get("zones") or NETWORK["zones"])
        if name == "prioritize_repairs":
            sys_cfg = NETWORK.get("system") or {}
            return engine.prioritize(
                args.get("leaks") or NETWORK["leaks"],
                specific_power=float(sys_cfg.get("specific_power_kwh_m3") or engine.DEFAULT_SP),
                hours=float(sys_cfg.get("hours_per_year") or engine.DEFAULT_HOURS),
                price=float(sys_cfg.get("price_yuan_kwh") or engine.DEFAULT_PRICE),
                top_n=int(args.get("top_n") or 5),
            )
        if name == "saving_potential":
            return engine.saving_potential(
                float(args["leak_flow"]), float(args["supply_flow"]),
                target_rate=float(args.get("target_rate") or 0.10),
            )
        if name == "pressure_reduction":
            return engine.pressure_reduction(
                float(args["p_now"]), float(args["p_target"]), float(args["total_flow"]),
            )
        return {"error": f"未知工具 {name}"}
    except (KeyError, ValueError, TypeError) as e:
        return {"error": f"参数不完整或格式错误：{e}"}


# ------------------------------------------------------------------ LLM 通路
def _post_json(url: str, payload: dict, api_key: str, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def llm_available() -> bool:
    return bool(LLM_BASE_URL and LLM_API_KEY and LLM_MODEL)


def chat_with_llm(messages: list[dict], max_rounds: int = 4) -> dict:
    """标准 function calling 循环"""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    trace = []
    for _ in range(max_rounds):
        payload = {
            "model": LLM_MODEL,
            "messages": msgs,
            "tools": TOOLS,
            "temperature": 0.2,
        }
        resp = _post_json(f"{LLM_BASE_URL}/chat/completions", payload, LLM_API_KEY)
        choice = resp["choices"][0]["message"]
        tool_calls = choice.get("tool_calls") or []
        if not tool_calls:
            return {"reply": choice.get("content", ""), "trace": trace, "mode": "llm"}
        msgs.append(choice)
        for tc in tool_calls:
            fn = tc["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = execute_tool(fn["name"], args)
            trace.append({"tool": fn["name"], "args": args, "result": result})
            msgs.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": json.dumps(result, ensure_ascii=False),
            })
    return {"reply": "算了几轮还没收敛，请把参数一次性给全。", "trace": trace, "mode": "llm"}


# ------------------------------------------------------------------ 兜底通路
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _nums(text: str) -> list[float]:
    return [float(x) for x in _NUM.findall(text)]


def chat_fallback(text: str) -> dict:
    """无 LLM 时的规则引擎：关键词命中 → 调同一个工具 → 模板化回答"""
    t = text.strip()
    trace = []

    if not t:
        return {"reply": "把工况发我，或者问一句“先修哪儿”。", "trace": [], "mode": "rule"}

    if any(k in t for k in ["关小", "关阀", "总阀", "降低压力", "降压", "调低压力"]):
        r = engine.pressure_reduction(0.7, 0.6, 50)
        trace.append({"tool": "pressure_reduction", "args": {"p_now": 0.7}, "result": r})
        return {"reply": (
            "先说结论：关小总阀治不了泄漏。\n\n"
            "关阀是增加阻力，气该漏还是漏，只是末端压力更低、设备更没劲。"
            "真正能省电的是**降低供气压力**，经验上每降 1 bar 约省 7%（示例：0.7→0.6 MPa 约省 7%，"
            "年省 1.3 万度）。\n\n"
            "但降压力有前提：所有用气设备的最低工作压力必须满足，管路压损也会变大。\n\n"
            "顺序建议：先修漏点（回收期普遍不到 1 年），再谈降压。"
        ), "trace": trace, "mode": "rule"}

    if any(k in t for k in ["编", "随便", "估一个", "大概给个数", "你就按"]):
        return {"reply": (
            "这个我不编。容积、压力、修复价格都得有现场依据，编出来的数看着漂亮，"
            "到了评审或现场一问就穿帮。\n\n请给我：容积 V、起始压力、终止压力、压降时间。"
        ), "trace": [], "mode": "rule"}

    if any(k in t for k in ["分区", "支路", "定位", "哪个车间", "哪一片"]):
        r = engine.zone_balance(NETWORK["zones"])
        trace.append({"tool": "zone_balance", "args": {}, "result": r})
        rows = "\n".join(
            f"· {z['name']}：进口 {z['header_flow']}，支路合计 {z['branch_sum']}，"
            f"差额 {z['gap']}（占差额 {z['share_of_total_gap']}%）"
            for z in r["zones"]
        )
        return {"reply": (
            f"【结论】差额最大的是 {r['top']}，系统未计量合计 {r['total_gap']} m³/min。\n\n"
            f"【分区明细】\n{rows}\n\n"
            f"【下一步】先从 {r['top']} 做超声听漏，再逐段关阀二分缩小范围。"
        ), "trace": trace, "mode": "rule"}

    if any(k in t for k in ["先修", "优先", "排序", "清单", "先改", "回本"]):
        r = engine.prioritize(NETWORK["leaks"])
        rows = "\n".join(
            f"{i['rank']}. {i['location']}｜漏量 {i['flow']} m³/min｜投资 {i['cost']:.0f} 元｜"
            f"年省 {i['annual_save']:.0f} 元｜回收 {i['payback_days']:.0f} 天回本"
            for i in r["top"]
        )
        s = r["top_summary"]
        return {"reply": (
            f"【结论】先修下面这 {s['count']} 处，投资 {s['invest']:.0f} 元，"
            f"一年能省 {s['annual_save']:.0f} 元。\n\n{rows}\n\n"
            "【判断依据】按静态回收期排序，不看漏量大小——漏得多但修起来贵的，排后面。"
        ), "trace": trace, "mode": "rule"}

    nums = _nums(t)
    decay_words = ["保压", "压降", "泄漏量", "漏了", "漏多少", "算一下", "降到", "分钟", "v=", "V="]
    if any(k in t for k in decay_words):
        if len(nums) >= 4:
            v, p1, p2, tm = nums[:4]
            try:
                r = engine.decay_report(v, p1, p2, tm)
            except ValueError as e:
                return {"reply": f"参数有问题：{e}", "trace": [], "mode": "rule"}
            trace.append({"tool": "decay_test", "args": {}, "result": r})
            return {"reply": (
                f"【结论】泄漏 {r['leak_flow_m3min']} m³/min，一年漏掉 "
                f"{r['annual_kwh']:.0f} 度电、{r['annual_cost']:.0f} 元。\n\n"
                f"【计算过程】Q = V×(P1−P2)/(t×1.013) = {v}×({p1}−{p2})/({tm}×1.013)\n\n"
                f"【换算】年漏气 {r['annual_volume_m3']:.0f} m³，"
                f"按比功率 0.12 kWh/m³、6000 h/年、0.65 元/度计。\n\n"
                "【下一步】补一个总产气量，我就能算出泄漏率和等级；再补分区流量，就能定位。"
            ), "trace": trace, "mode": "rule"}
        return {"reply": (
            "做保压试验需要四个数：容积 V（m³）、起始压力 P1（bar）、终止压力 P2（bar）、"
            "压降时间 t（min）。\n\n例如：V=10，7 降到 6，用了 5 分钟。\n"
            "有总产气量的话一起给我，能顺带算泄漏率。"
        ), "trace": [], "mode": "rule"}

    return {"reply": (
        "我能做四件事：\n"
        "1. 保压试验算泄漏量——给我 V、P1、P2、t\n"
        "2. 分区流量平衡找漏区——给我各区的进口与支路流量\n"
        "3. 排修复优先级——给我漏点位置、漏量、修复成本\n"
        "4. 算达标节电潜力——给我当前泄漏率与目标值\n\n"
        "示例：V=10，7 降到 6，5 分钟。"
    ), "trace": [], "mode": "rule"}


def chat(messages: list[dict]) -> dict:
    """对外入口：有 LLM 走 LLM，出错自动回落规则引擎"""
    if llm_available():
        try:
            return chat_with_llm(messages)
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, TimeoutError, OSError) as e:
            last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
            out = chat_fallback(last)
            out["note"] = f"模型接口不可用，已切换到本地规则模式（{type(e).__name__}）"
            return out
    last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    return chat_fallback(last)
