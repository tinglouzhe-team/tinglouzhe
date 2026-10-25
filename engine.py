# -*- coding: utf-8 -*-
"""
听漏者 · 计算引擎
==================
纯函数，无第三方依赖，方便单元测试和移植。

四个核心能力：
1. 保压（压降）法测算系统总泄漏量          —— ISO 11011 常用做法
2. 分区流量平衡定位泄漏区段
3. 漏点修复优先级排序（按回收期）
4. 泄漏率判级与达标节电潜力

所有公式都在 docstring 里写清楚，答辩时照着念即可。
"""

from __future__ import annotations

P_ATM = 1.013          # 标准大气压 bar
CO2_FACTOR = 0.57      # kgCO2/kWh（全国电网平均，引用时注明以最新公布为准）
DEFAULT_HOURS = 6000   # 年运行小时
DEFAULT_PRICE = 0.65   # 电价 元/kWh
DEFAULT_SP = 0.12      # 空压机比功率 kWh/m3（7-8 bar 典型值 0.10-0.12）

# 泄漏率判级（行业经验值，用于演示，方案书需注明来源）
GRADE_TABLE = [
    (0.10, "优", "低于 10%，维护良好"),
    (0.20, "良", "10%—20%，处于行业常见水平，仍有改善空间"),
    (0.30, "差", "20%—30%，明显偏高，建议立即排查"),
    (1.00, "极差", "高于 30%，属于失控状态，应先做全厂普查"),
]


# ------------------------------------------------------------------ 1. 保压法
def leak_flow_from_decay(v_m3: float, p1_bar: float, p2_bar: float,
                         t_min: float, p_atm: float = P_ATM) -> float:
    """由压降试验求泄漏流量（自由空气，m3/min）

    原理：储气罐 + 管路容积 V 在 t 分钟内从 P1 降到 P2，
         减少的气体量等于泄漏量。

        Q = V × (P1 − P2) / (t × P0)

    注意单位：V 用 m3，P 用 bar（表压或绝压均可，只要 P1、P2 同口径），
             t 用 min，P0 取 1.013 bar。
    """
    if v_m3 <= 0 or t_min <= 0:
        raise ValueError("容积和压降时间必须大于 0")
    if p1_bar <= p2_bar:
        raise ValueError("起始压力必须高于终止压力（否则不是压降试验）")
    return v_m3 * (p1_bar - p2_bar) / (t_min * p_atm)


def decay_report(v_m3: float, p1: float, p2: float, t_min: float,
                 supply_flow: float | None = None,
                 specific_power: float = DEFAULT_SP,
                 hours: float = DEFAULT_HOURS,
                 price: float = DEFAULT_PRICE) -> dict:
    """保压试验完整测算：泄漏量 → 年损失 → 判级"""
    q = leak_flow_from_decay(v_m3, p1, p2, t_min)
    annual_volume = q * 60 * hours
    annual_kwh = annual_volume * specific_power
    annual_cost = annual_kwh * price
    result = {
        "leak_flow_m3min": round(q, 3),
        "leak_flow_m3h": round(q * 60, 2),
        "annual_volume_m3": round(annual_volume, 0),
        "annual_kwh": round(annual_kwh, 0),
        "annual_cost": round(annual_cost, 0),
        "annual_co2_t": round(annual_kwh * CO2_FACTOR / 1000, 1),
        "assumptions": {
            "specific_power_kwh_m3": specific_power,
            "hours_per_year": hours,
            "price_yuan_kwh": price,
        },
        "warnings": [],
    }
    if q > 10:
        result["warnings"].append(
            f"泄漏量 {q:.1f} m³/min 偏大（超过 10），请确认容积是否包含了管路总容积，"
            "或压降时间是否过短。"
        )
    if supply_flow:
        rate = q / supply_flow if supply_flow > 0 else 0
        result["leak_rate"] = round(rate * 100, 1)
        result["grade"] = _grade(rate)
        if rate > 0.40:
            result["warnings"].append(
                "泄漏率超过 40%，不符合常见工况，请复核总产气量或测试数据。"
            )
    return result


def _grade(rate: float) -> dict:
    for limit, name, note in GRADE_TABLE:
        if rate < limit:
            return {"level": name, "note": note}
    return {"level": "极差", "note": "数据异常，请复核"}


# ------------------------------------------------------------------ 2. 分区定
def zone_balance(zones: list[dict]) -> dict:
    """分区流量平衡：进口总表 − 支路合计 = 该区未计量（泄漏）流量

    zones 每项：{"name": "3号车间", "header_flow": 18.5, "branches": [5.0, 4.2, 3.1]}
    """
    rows = []
    total_gap = 0.0
    for z in zones:
        header = float(z.get("header_flow", 0))
        branches = [float(b) for b in z.get("branches", [])]
        branch_sum = sum(branches)
        gap = header - branch_sum
        total_gap += gap
        rows.append({
            "name": z.get("name", "未命名"),
            "header_flow": round(header, 2),
            "branch_sum": round(branch_sum, 2),
            "gap": round(gap, 3),
            "gap_pct": round(gap / header * 100, 1) if header > 0 else 0.0,
        })
    for r in rows:
        r["share_of_total_gap"] = round(r["gap"] / total_gap * 100, 1) if total_gap > 0 else 0.0
    rows.sort(key=lambda x: -x["gap"])
    return {
        "total_gap": round(total_gap, 3),
        "zones": rows,
        "top": rows[0]["name"] if rows else None,
        "warnings": _zone_warnings(rows),
    }


def _zone_warnings(rows: list[dict]) -> list[str]:
    w = []
    for r in rows:
        if r["gap"] < 0:
            w.append(f"{r['name']}：支路合计大于进口总表（{r['gap']}），"
                     "计量口径或表计方向可能有问题，需现场核对。")
        elif r["header_flow"] > 0 and r["gap_pct"] > 30:
            w.append(f"{r['name']}：未计量比例 {r['gap_pct']}% 偏高，优先排查。")
    return w


# ------------------------------------------------------------------ 3. 排序
def prioritize(leaks: list[dict],
               specific_power: float = DEFAULT_SP,
               hours: float = DEFAULT_HOURS,
               price: float = DEFAULT_PRICE,
               top_n: int = 5) -> dict:
    """漏点修复优先级：按静态回收期从短到长排序

    leaks 每项：{"location": "3号车间-东侧法兰", "flow": 0.35, "cost": 800}
    flow 单位 m3/min，cost 单位 元
    """
    items = []
    warnings = []
    for lk in leaks:
        q = float(lk.get("flow", 0))
        cost = float(lk.get("cost", 0))
        annual_kwh = q * 60 * hours * specific_power
        annual_save = annual_kwh * price
        # 投资没填，回收期就不可算——不猜，标成 None 并排到最后
        payback = (cost / annual_save) if (cost > 0 and annual_save > 0) else None
        if cost <= 0:
            warnings.append(f"{lk.get('location', '未命名')}：修复投资未提供，"
                            "无法计算回收期，已排在清单末尾。")
        items.append({
            "location": lk.get("location", "未命名"),
            "flow": round(q, 3),
            "cost": cost,
            "annual_kwh": round(annual_kwh, 0),
            "annual_save": round(annual_save, 0),
            "payback_years": round(payback, 2) if payback is not None else None,
            "roi": round(annual_save / cost, 2) if cost > 0 else None,
            "payback_days": round(payback * 365, 0) if payback is not None else None,
        })
    items.sort(key=lambda x: (x["payback_years"] is None, x["payback_years"] or 0))
    for i, it in enumerate(items, 1):
        it["rank"] = i
    chosen = [i for i in items if i["payback_years"] is not None][:top_n]
    return {
        "items": items,
        "top": chosen,
        "top_summary": {
            "count": len(chosen),
            "invest": round(sum(i["cost"] for i in chosen), 0),
            "annual_save": round(sum(i["annual_save"] for i in chosen), 0),
            "flow": round(sum(i["flow"] for i in chosen), 3),
        },
        "warnings": warnings or (["没有可排序的漏点数据"] if not items else []),
    }


# ------------------------------------------------------------------ 4. 达标潜力
def saving_potential(leak_flow: float, supply_flow: float,
                     target_rate: float = 0.10,
                     specific_power: float = DEFAULT_SP,
                     hours: float = DEFAULT_HOURS,
                     price: float = DEFAULT_PRICE) -> dict:
    """把泄漏率降到目标值可节省的电量

    注意：这里只算"少漏掉的气"，不含因压力优化带来的额外收益。
    """
    if supply_flow <= 0:
        raise ValueError("总产气量必须大于 0")
    current = leak_flow / supply_flow
    allowed = target_rate * supply_flow
    cut = max(leak_flow - allowed, 0)
    annual_kwh = cut * 60 * hours * specific_power
    return {
        "current_rate": round(current * 100, 1),
        "target_rate": round(target_rate * 100, 1),
        "cut_flow": round(cut, 3),
        "annual_kwh": round(annual_kwh, 0),
        "annual_save": round(annual_kwh * price, 0),
        "annual_co2_t": round(annual_kwh * CO2_FACTOR / 1000, 1),
        "reachable": cut > 0,
    }


# ------------------------------------------------------------------ 5. 降压
def pressure_reduction(p_now: float, p_target: float,
                       total_flow: float,
                       specific_power: float = DEFAULT_SP,
                       hours: float = DEFAULT_HOURS,
                       price: float = DEFAULT_PRICE) -> dict:
    """降低供气压力的节电估算（经验法）

    经验规律：供气压力每降低 1 bar，空压机能耗约下降 7%—8%（取 7%）。
    前提：末端设备的最低工作压力允许，且管路压损不会因此变大。
    """
    if p_target >= p_now:
        raise ValueError("目标压力应低于当前压力")
    dp = p_now - p_target
    ratio = 0.07 * dp
    annual_kwh = total_flow * 60 * hours * specific_power * ratio
    return {
        "pressure_drop_bar": round(dp, 2),
        "saving_ratio": round(ratio * 100, 1),
        "annual_kwh": round(annual_kwh, 0),
        "annual_save": round(annual_kwh * price, 0),
        "note": "仅估算空压机能耗下降，未计末端设备出力不足的风险；"
                "实际实施前必须确认所有用气设备的最低工作压力。",
    }
