# 电商进销存推算与库存调控 · 方法论

> 配套 `scripts/demand_forecast.py` 与 `scripts/inventory_allocation.py`。
> 所有系数均为可调参数，下表给的是默认值与调参建议。

---

## A. 销售推算（需求侧）

### A.1 输入
| 字段 | 含义 | 口径 |
|---|---|---|
| `total30` | 近 30 天销量（件） | 自然 30 天，含大促需标注 |
| `total7` | 近 7 天销量（件） | 最近 7 天，口径同 total30 |
| `available` | 当前可用库存（件） | 用**实际可用**（扣锁单/预留/团购占用） |
| `in_transit` | 在途库存（件，可选） | 已下单未入仓 |
| `lead_time` | 补货周期（天） | 下单到入仓可售 |
| `safety_days` | 安全天数（天） | 覆盖波动的缓冲，默认 7 |
| `target_cover` | 目标覆盖天数（天） | 想保有多久的货，默认 30 |

### A.2 公式
```
avg30 = total30 / 30
avg7  = total7  / 7
momentum = avg7 / avg30                      # 势能：>1 起势，<1 回落

# 预测日均：默认加权；势能极端时自动偏向 7 天
if momentum > 1.25:   predicted = avg7 * min(momentum, 1.8)   # 起势，跟势能但封顶防虚高
elif momentum < 0.8:  predicted = avg30 * 0.9                 # 回落，保守且不补
else:                 predicted = 0.4*avg30 + 0.6*avg7        # 平稳，加权

DOI        = available / predicted            # 可售天数（唯一真相尺）
safety     = predicted * safety_days
ROP        = predicted * lead_time + safety   # 补货点
target     = predicted * target_cover
replenish  = max(0, target - available - in_transit)
turnover   ≈ DOI                               # 周转天数（越长越积压）
```

### A.3 三色健康度
| 档 | 条件 | 动作 |
|---|---|---|
| 🔴 红 | DOI < lead_time | 断货风险，紧急补货/跨区调拨 |
| 🟡 黄 | lead_time ≤ DOI < lead_time + safety_days | 计划补货（已近补货点） |
| 🟢 绿 | lead_time+safety_days ≤ DOI ≤ target_cover | 健康，维持 |
| 🟣 紫 | DOI > target_cover × 1.5 | 积压预警，转滞销/清仓 |

### A.4 调参建议
- **起势品**：`target_cover` 拉到 45~60（大促前），w7 权重上提。
- **回落/清仓品**：关补货（`replenish=0`），DOI 高即紫牌处理。
- **高波动品**（momentum 抖动大）：`safety_days` 提到 10~14。
- **势能封顶**：momentum 上限 1.8，避免单周活动导致过度补货。

### A.5 示例
```
total30=3000, total7=800, available=1500, lead_time=7, safety_days=7, target_cover=30
avg30=100, avg7≈114.3, momentum=1.14（平稳）
predicted = 0.4*100 + 0.6*114.3 = 108.6 件/天
DOI = 1500 / 108.6 = 13.8 天
safety = 108.6*7 = 760；ROP = 108.6*7 + 760 = 1521
target = 108.6*30 = 3258；replenish = 3258 - 1500 = 1758 件
健康度：lead_time(7) ≤ 13.8 < 7+7=14 → 🟡 黄，计划补货
```

---

## B. 库存调控（供给侧：大区 → 链接 / 组合倍数）

### B.1 输入
```json
{
  "regions": [ {"region":"华东","available":1200}, {"region":"华南","available":600} ],
  "links": [
    {"link_id":"天猫主链接", "demand_units":800, "combo_multiple":1, "priority":1, "prefer_region":"华东"},
    {"link_id":"拼多多2件装", "demand_units":600, "combo_multiple":2, "priority":2},
    {"link_id":"小红书3件bundles", "demand_units":300, "combo_multiple":3, "priority":3}
  ]
}
```

### B.2 算法步骤
1. **折算可售组数**
   ```
   required_groups = ceil(demand_units / combo_multiple)
   required_units  = required_groups * combo_multiple      # 取整损耗
   ```
   例：小红书 demand=300、倍数=3 → required_groups=100 组，耗 300 件。

2. **优先级配额（库存不足时 rationing）**
   总可用 < 总需求时按比例缩：
   | priority | 含义 | 默认配比 |
   |---|---|---|
   | 1 核心 | 主推/高毛利/大促 | 1.00（拿满） |
   | 2 腰部 | 常规 | `waist_ratio`=0.8 |
   | 3 长尾 | 长尾 | `tail_ratio`=0.5 |
   充足时全部拿满。

3. **就近分配**
   - 链接有 `prefer_region` → 优先从该大区取（就近，省物流）。
   - 无偏好 → 大区按可用量降序填充。
   - 就近不足且链接 priority 高 → 允许跨区补足（记为 `cross_region=true`，提示物流成本）。

4. **按倍数取整**：每个链接实收件数必须是 `combo_multiple` 的整数倍。

5. **剩余回池**：未分配库存留在大区 `leftover`，不压给低效链接。

6. **产出**：
   - `allocation[region][link] = 件数`
   - 各链接 `received_groups / received_units / DOI_after`
   - 标记 `under_supplied`（欠供）、`over_supplied`（超供，极少发生）
   - 各大区 `leftover`
   - `cross_region` 提示

### B.3 分配后 DOI
```
DOI_after(link) = received_units / (demand_units / 覆盖天数窗)
```
若 `received_units < demand_units` → 该链接 DOI_after 不足窗长 → 标欠供，触发跨区/紧急补货。

### B.4 总监决策摘要（脚本自动生成）
- 哪些链接**保供满**（绿）、哪些**欠供**（红，需跨区/补货）。
- 哪个大区**剩货最多**（可下调该大区后续补货或调出）。
- 是否发生**跨区调拨**及涉及链接（评估物流成本是否值得）。
- 组合倍数是否导致某链接"件数够但组数不够"（典型 2/3 件装坑）。

### B.5 示例（库存不足场景）
```
regions: 华东 1200, 华南 600  → 总可用 1800
links 需求折件: 天猫800(×1) + 拼多多600(×2→300组/600件) + 小红书300(×3→100组/300件) = 1700 件
总需求 1700 < 可用 1800 → 充足，全部拿满
分配：天猫主链接从华东拿 800（prefer）；拼多多从华南拿 600；小红书从华东拿 300；华东剩 100、华南剩 0。
```
若可用仅 1200（不足）：核心天猫拿满 800；腰部拼多多拿 600×0.8=480 件(240组)；长尾小红书拿 300×0.5=150 件(50组)；剩余 1200-800-480-150=-230 → 仍不足，继续按比例缩减或标记小红书严重欠供。

---

## C. 全局注意
- **可用口径**：用 `actualAvailable`（实际可用），不是总在库 `totalNum`。
- **倍数换算**：demand 用"件"，分配用"组×倍数=件"，全程显式换算。
- **势能封顶**：momentum 上限 1.8，防单周活动虚高。
- **无依赖**：脚本仅用标准库，python3 直接跑。
