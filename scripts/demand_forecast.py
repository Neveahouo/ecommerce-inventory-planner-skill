#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电商需求推算（销售侧）
基于 近30天 / 近7天 销量，推算预测日均、可售天数(DOI)、安全库存、补货点(ROP)、
建议补货量、周转天数，并给出三色健康度。

仅用标准库。用法：
  python demand_forecast.py --input sample_data.json [--sku SKU]
  echo '{"total30":3000,"total7":800,"available":1500}' | python demand_forecast.py --stdin
"""
import argparse, json, sys, math


def forecast(total30, total7, available, in_transit=0,
             lead_time=7, safety_days=7, target_cover=30, momentum_cap=1.8):
    avg30 = total30 / 30.0
    avg7 = total7 / 7.0
    momentum = (avg7 / avg30) if avg30 > 0 else 1.0

    if momentum > 1.25:
        predicted = avg7 * min(momentum, momentum_cap)   # 起势：跟势能但封顶防虚高
    elif momentum < 0.8:
        predicted = avg30 * 0.9                          # 回落：保守且不补
    else:
        predicted = 0.4 * avg30 + 0.6 * avg7             # 平稳：加权

    if predicted <= 0:
        predicted = 0.0001

    doi = available / predicted
    safety = predicted * safety_days
    rop = predicted * lead_time + safety
    target = predicted * target_cover
    replenish = max(0.0, target - available - in_transit)
    turnover = doi

    if doi < lead_time:
        health, reason = "red", "DOI < 补货周期，断货风险，紧急补货/跨区调拨"
    elif doi < lead_time + safety_days:
        health, reason = "yellow", "已近补货点，计划补货"
    elif doi <= target_cover:
        health, reason = "green", "健康，维持"
    else:
        health, reason = "purple", "DOI 超目标覆盖1.5倍，积压预警，转滞销/清仓"

    return {
        "avg30_per_day": round(avg30, 2),
        "avg7_per_day": round(avg7, 2),
        "momentum": round(momentum, 3),
        "predicted_daily": round(predicted, 2),
        "doi_days": round(doi, 1),
        "safety_stock": round(safety, 1),
        "reorder_point": round(rop, 1),
        "target_stock": round(target, 1),
        "suggested_replenish": round(replenish, 1),
        "turnover_days": round(turnover, 1),
        "health": health,
        "health_reason": reason,
    }


def load_input(args):
    if args.stdin:
        data = json.load(sys.stdin)
    else:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
    # 支持单对象 或 {"skus":[...]} 或 列表
    if isinstance(data, list):
        skus = data
    elif isinstance(data, dict) and "skus" in data:
        skus = data["skus"]
        # 顶层默认参数
        for k in ("lead_time", "safety_days", "target_cover"):
            if k in data:
                for s in skus:
                    s.setdefault(k, data[k])
    else:
        skus = [data]
    return skus


def main():
    ap = argparse.ArgumentParser(description="电商需求推算")
    ap.add_argument("--input", help="JSON 文件路径（含 skus 或单个对象）")
    ap.add_argument("--stdin", action="store_true", help="从标准输入读 JSON")
    ap.add_argument("--sku", help="只输出指定 sku")
    ap.add_argument("--lead-time", type=float, default=7)
    ap.add_argument("--safety-days", type=float, default=7)
    ap.add_argument("--target-cover", type=float, default=30)
    args = ap.parse_args()

    if not args.input and not args.stdin:
        ap.error("需要 --input 或 --stdin")

    skus = load_input(args)
    results = []
    for s in skus:
        if args.sku and s.get("sku") != args.sku:
            continue
        r = forecast(
            s["total30"], s["total7"], s["available"], s.get("in_transit", 0),
            s.get("lead_time", args.lead_time),
            s.get("safety_days", args.safety_days),
            s.get("target_cover", args.target_cover),
        )
        r["sku"] = s.get("sku", "?")
        results.append(r)

    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    # 可读摘要
    print("\n=== 可读摘要 ===")
    health_icon = {"red": "🔴", "yellow": "🟡", "green": "🟢", "purple": "🟣"}
    for r in results:
        print(f"[{health_icon[r['health']]} {r['health']}] {r['sku']}: "
              f"预测日均 {r['predicted_daily']} 件 | DOI {r['doi_days']} 天 | "
              f"建议补货 {r['suggested_replenish']} 件 | {r['health_reason']}")


if __name__ == "__main__":
    main()
