#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电商库存调控（供给侧分配）
单条码：把分散在多个大区的可用库存，按"销量需求 + 组合倍数 + 战略优先级 + 就近"，
拆分到多个链接（店铺/渠道）。输出 region×link 分配矩阵、各链接实收与分配后 DOI、
欠供/跨区标记、大区剩余、总监式决策摘要。

仅用标准库。用法：
  python inventory_allocation.py --input sample_data.json
"""
import argparse, json, sys, math


def floor_to_multiple(x, m):
    if m <= 0:
        return x
    return int(math.floor(x / m)) * m


def allocate(regions, links, waist_ratio=0.8, tail_ratio=0.5, coverage_window=30):
    # 大区库存
    region_stock = {r["region"]: int(r["available"]) for r in regions}
    region_order = sorted(region_stock, key=lambda k: region_stock[k], reverse=True)

    # 各链接需求折算
    for l in links:
        combo = int(l["combo_multiple"])
        l["_combo"] = combo
        req_groups = math.ceil(l["demand_units"] / combo) if combo > 0 else 0
        l["required_groups"] = req_groups
        l["required_units"] = req_groups * combo

    total_available = sum(region_stock.values())
    total_required = sum(l["required_units"] for l in links)
    shortage = total_required > total_available

    # 计算各链接 claim（库存不足时按优先级配额）
    priority_cap = {1: 1.0, 2: waist_ratio, 3: tail_ratio}
    for l in links:
        cap = priority_cap.get(int(l.get("priority", 1)), 1.0)
        if shortage:
            claim = floor_to_multiple(l["required_units"] * cap, l["_combo"])
        else:
            claim = l["required_units"]
        l["claim_units"] = claim

    # 按优先级升序（核心先拿），同级按 claim 降序
    ordered = sorted(links, key=lambda l: (int(l.get("priority", 1)), -l["claim_units"]))

    allocation = {r: {} for r in region_stock}   # region -> {link_id: units}
    link_result = {}

    for l in ordered:
        need = l["claim_units"]
        combo = l["_combo"]
        prefer = l.get("prefer_region")
        got = 0
        used_regions = []
        cross = False

        # 1) 优先就近大区
        if prefer and region_stock.get(prefer, 0) > 0:
            take = min(need - got, region_stock[prefer])
            take = floor_to_multiple(take, combo)
            if take > 0:
                allocation[prefer][l["link_id"]] = allocation[prefer].get(l["link_id"], 0) + take
                region_stock[prefer] -= take
                got += take
                used_regions.append(prefer)

        # 2) 其余大区按可用量降序补
        for r in region_order:
            if got >= need:
                break
            if region_stock[r] <= 0:
                continue
            if prefer and r == prefer:
                continue
            take = min(need - got, region_stock[r])
            take = floor_to_multiple(take, combo)
            if take > 0:
                allocation[r][l["link_id"]] = allocation[r].get(l["link_id"], 0) + take
                region_stock[r] -= take
                got += take
                used_regions.append(r)
                if prefer and r != prefer:
                    cross = True

        received_groups = got // combo if combo > 0 else 0
        # 分配后 DOI（用需求窗换算：demand_units 对应 coverage_window 天）
        daily = l["demand_units"] / coverage_window if coverage_window > 0 else 0
        doi_after = (got / daily) if daily > 0 else (float("inf") if got > 0 else 0)
        # 真欠供：连"按优先级的配额"都没拿满（库存实在不够）；
        # 被配额(rationed)：拿到了配额但低于原始需求（短缺时腰部/长尾按比例缩）。
        under = got < l["claim_units"]
        rationed = (not under) and (l["claim_units"] < l["required_units"])

        link_result[l["link_id"]] = {
            "combo_multiple": combo,
            "required_groups": l["required_groups"],
            "required_units": l["required_units"],
            "claim_units": l["claim_units"],
            "allocated_groups": received_groups,
            "allocated_units": got,
            "fill_ratio": round(got / l["required_units"], 3) if l["required_units"] else 1.0,
            "claim_ratio": round(got / l["claim_units"], 3) if l["claim_units"] else 1.0,
            "doi_after_days": (round(doi_after, 1) if doi_after != float("inf") else None),
            "under_supplied": under,
            "rationed": rationed,
            "cross_region": (cross if prefer else False),
            "used_regions": used_regions,
        }

    region_leftover = {r: region_stock[r] for r in region_stock}
    cross_links = [lid for lid, v in link_result.items() if v["cross_region"]]
    under_links = [lid for lid, v in link_result.items() if v["under_supplied"]]
    leftover_total = sum(region_leftover.values())

    summary = build_summary(link_result, region_leftover, cross_links, under_links,
                            total_available, total_required, leftover_total)

    return {
        "total_available": total_available,
        "total_required_units": total_required,
        "shortage": shortage,
        "allocation": allocation,
        "links": link_result,
        "region_leftover": region_leftover,
        "cross_region_links": cross_links,
        "under_supplied_links": under_links,
        "leftover_total": leftover_total,
        "summary": summary,
    }


def build_summary(link_result, region_leftover, cross_links, under_links,
                  total_available, total_required, leftover_total):
    lines = []
    lines.append(f"总可用 {total_available} 件，总需求 {total_required} 件，"
                 f"{'库存不足→已按优先级配额' if total_available < total_required else '库存充足→全部拿满'}，"
                 f"大区池剩余 {leftover_total} 件。")
    full = [lid for lid, v in link_result.items() if not v["under_supplied"] and not v["rationed"]]
    rationed = [lid for lid, v in link_result.items() if v["rationed"]]
    if full:
        lines.append(f"✅ 保供满：{', '.join(full)}")
    if rationed:
        lines.append(f"🟡 按配额满足但低于原始需求（短缺被按比例缩）：{', '.join(rationed)}")
    if under_links:
        lines.append(f"🔴 欠供需补/跨区：{', '.join(under_links)}")
    if cross_links:
        lines.append(f"↔️ 发生跨区调拨：{', '.join(cross_links)}（评估物流成本是否值得）")
    big_left = sorted([(r, q) for r, q in region_leftover.items() if q > 0],
                      key=lambda x: -x[1])
    if big_left:
        lines.append("🟣 剩货大区：" + "、".join(f"{r}{q}件" for r, q in big_left))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="电商库存调控：大区→链接/组合倍数拆分")
    ap.add_argument("--input", required=True, help="JSON 文件路径")
    ap.add_argument("--waist-ratio", type=float, default=0.8)
    ap.add_argument("--tail-ratio", type=float, default=0.5)
    ap.add_argument("--coverage-window", type=float, default=30)
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)
    res = allocate(data["regions"], data["links"],
                   args.waist_ratio, args.tail_ratio, args.coverage_window)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print("\n=== 总监决策摘要 ===")
    print(res["summary"])


if __name__ == "__main__":
    main()
