# ecommerce-inventory-planner

电商进销存推算与库存调控 · WorkBuddy 可安装 Skill

把电商总监做「进销存」时脑子里的两套算盘，落成可执行的算法与脚本：

1. **销售推算（需求侧）**：用 30 天 / 7 天销售，算出每个 SKU 真实「每天卖多少、还能卖几天、该补多少」。
2. **库存调控（供给侧分配）**：当库存有限时，按「可用大区 → 不同链接（店铺/渠道）→ 不同组合倍数」做最优拆分，让对的货去对的地方。

> 所有业务系数（安全天数、补货周期、组合倍数、优先级配比）都是**可调参数**，不写死。先跑通逻辑，再按品类/活动微调。

---

## 安装

作为 WorkBuddy 用户级 skill（推荐）：

```bash
# 把本仓库放到用户 skill 目录
cp -r ecommerce-inventory-planner ~/.workbuddy/skills/
```

或在 WorkBuddy 里通过 `marketplace-skill-installer` / `skill-creator` 安装。
纯代码使用（不要 skill 格式）也可直接 `git clone` 后跑 `scripts/` 里的 Python。

---

## 模块一：销售推算

```bash
python scripts/demand_forecast.py --input scripts/sample_data.json
# 或单对象标准输入
echo '{"total30":3000,"total7":800,"available":1500}' | python scripts/demand_forecast.py --stdin
```

输出每个 SKU 的：预测日均、势能(momentum)、可售天数 DOI、安全库存、补货点 ROP、建议补货量、周转天数，以及三色健康度（🔴断货 / 🟡计划补货 / 🟢健康 / 🟣积压）。

**核心公式**（详见 [`references/methodology.md`](references/methodology.md)）：
```
avg30 = total30/30, avg7 = total7/7
momentum = avg7/avg30                      # >1 起势, <1 回落
predicted = (起势? avg7·min(momentum,1.8) : 回落? avg30·0.9 : 0.4·avg30+0.6·avg7)
DOI = available / predicted                # 可售天数（唯一真相尺）
safety = predicted × safety_days
ROP = predicted × lead_time + safety
建议补货量 = max(0, predicted × target_cover − available − 在途)
```

---

## 模块二：库存调控（大区 → 链接 / 组合倍数）

```bash
python scripts/inventory_allocation.py --input scripts/sample_data.json
```

输入：各大区可用库存 `regions` + 各链接需求/组合倍数/优先级 `links`。
输出：region×link 分配矩阵、各链接实收组数/件数、分配后 DOI、欠供/被配额/跨区标记、大区剩余、总监式决策摘要。

**分配算法要点**：
1. 按组合倍数把需求折成「可售组数」（卖 2 件装 → 1 组=2 件，避免件/组混淆）。
2. 库存不足时按优先级配额：核心拿满、腰部默认 0.8、长尾默认 0.5。
3. 就近分配：优先 `prefer_region`，不足且优先级高才跨区（提示物流成本）。
4. 按倍数取整，剩余回大区池（不压给低效链接）。

---

## 示例数据

`scripts/sample_data.json` 同时包含 `skus`（推算示例）与 `regions`/`links`（分配示例，刻意构造库存不足场景演示优先级配额与跨区）。

---

## 目录

```
ecommerce-inventory-planner/
├── SKILL.md                      # WorkBuddy skill 指令（总监思维框架 + 两模块）
├── README.md
├── references/
│   └── methodology.md            # 完整公式、示例、调参建议、分配算法详解
├── scripts/
│   ├── demand_forecast.py        # 需求推算
│   ├── inventory_allocation.py   # 大区→链接/组合倍数拆分
│   └── sample_data.json          # 示例输入
└── LICENSE
```

## 依赖

仅 Python 3 标准库（json / csv / math / argparse）。无第三方依赖。

## License

MIT — 见 [LICENSE](LICENSE)。
