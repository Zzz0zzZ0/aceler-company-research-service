# Research, scoring, and report contract

## Input contract

Only a company name is required. Inputs may come from a spreadsheet, API, manual entry, database, or another business system and may omit website, LinkedIn, country, industry, rating, background, contacts, plant, or registration data. Supplied fields are identity hints to verify, not ground truth. Missing fields mean `unknown`; they are not negative evidence, do not reduce any scoring component, and do not justify a zero score or `其他/公开资料不足` role. Base the entity, operating role, process, and product mapping on the evidence gathered for this run.

Resolve entity scope semantically from the complete source context. Omitting an ordinary legal suffix is acceptable when the distinctive name, domain, address, brand, and business description reasonably identify the same operator. Evidence about a parent, group, brand, affiliate, division, or site may support the target's positioning when those signals establish a plausible operating relationship even if the legal link is not stated word for word; use `identity_status: ambiguous`, `research_status: partial`, and lower confidence for the unresolved relationship, but still score the supported substantive positioning. Do not transfer facts when the evidence points to a clearly different namesake, entity, or unrelated group operation.

## Evidence states

- `已确认`: a current, relevant source directly supports the company-specific claim.
- `推测`: a reasonable process/product inference exists, but the company-specific purchase or application is not published.
- `公开资料未确认`: the required fact was searched for but not established publicly.

Never convert a general industry convention into an `已确认` company purchase. A source proves only what it actually states. A refractory manufacturer's finished product or product-family listing proves its output, not its raw-material input. It can support a technically mapped raw-material direction, but that direction remains `推测` unless the source directly confirms the exact input, purchase, or use.

## Role definitions

### Operational role

- `终端用户`: operates a plant/process that consumes relevant products.
- `耐材生产商`: manufactures refractory shapes, monolithics, precast products, or related formulations.
- `材料生产商`: manufactures industrial minerals, ceramic/abrasive raw materials, metals, chemicals, or other relevant upstream or complementary materials.
- `贸易商`: buys/sells commodities or industrial materials, typically transaction-led and without a defined territory/service inventory role.
- `分销商`: resells specified products into an established territory/customer base, often with stock, logistics, technical service, or brand representation.
- `工程公司`: designs, specifies, installs, repairs, commissions, or procures for industrial projects.
- `同行`: substantially overlaps Aceler's supplier/trading scope and is not better described by a more concrete operating role.
- `其他/公开资料不足`: none of the above is supportable.

Decide the operational role in this order: first use evidence to identify the company's main revenue activity. Manufacturing refractory bricks, monolithics, precast products, or refractory formulations means `耐材生产商`; manufacturing relevant industrial minerals, ceramic/abrasive raw materials, metals, chemicals, or complementary materials means `材料生产商`; operating another production process that consumes relevant products means `终端用户`; designing, specifying, installing, repairing, commissioning, or procuring industrial projects means `工程公司`; reselling with an established territory, inventory, logistics, technical service, or brand representation means `分销商`; general material buying/selling means `贸易商`. Use `同行` only when the main supply scope overlaps Aceler's and no more specific operating role applies; use `其他/公开资料不足` only when evidence supports no specific role. `supplier`, `complete supplier`, `partner`, and `representative` do not by themselves prove manufacturing, and an equipment OEM is not `其他/公开资料不足` merely because it does not buy raw materials. `role_judgment.reason` must name the evidence-supported action (manufactures, resells, designs, installs, or operates), not only an industry label. Judge the commercial relationship to Aceler independently; it must not change the operational role, and a concrete operating role takes priority over `同行` or `其他/公开资料不足`.

A manufacturer of grinding wheels, cutting discs, coated abrasives, nonwoven abrasives, or polishing media is a `终端用户` of mapped abrasive grains. Do not label it `耐材生产商` unless it also manufactures refractory shapes, monolithics, precast refractory products, or refractory formulations.

### Commercial relationship to Aceler

- `潜在客户`: credible direct purchase/consumption or raw-material sourcing opportunity.
- `渠道合作伙伴`: credible resale, specification, project, installation, or customer-access opportunity.
- `供应合作伙伴`: credibly manufactures material Aceler could source, represent, or add to its supply network.
- `产品组合合作伙伴`: has complementary products or technical capabilities that create a credible joint portfolio route without evidence of direct supply.
- `同行`: primarily competes or overlaps, with no stronger supported buyer/channel route.
- `低匹配客户`: no meaningful process, product, or channel route is evidenced.

## Score rubric

Score catalog-grounded commercial relevance with five integer components. This includes direct consumption and credible channel, specification/project, complementary-supply, or portfolio-cooperation routes:

- `production_process_need` — 0–30: strength of the company's own process/application or of the downstream applications it demonstrably serves, supplies, specifies, installs, or distributes into.
- `catalog_fit` — 0–30: breadth and specificity of catalog overlap, whether as a technical input, handled product, specified material, complementary supply, or closely aligned portfolio.
- `consumption_intensity` — 0–20: likely material throughput or influence of the relevant operation, including self-consumption, recurring distribution, formulation, installation, or specification control.
- `demand_recurrence` — 0–10: likelihood that the operation, channel, or project portfolio creates recurring rather than one-off relevance.
- `company_role_fit` — 0–10: fit of the company as a direct customer, channel, project/specification influencer, complementary supplier, or relevant portfolio partner.

The validator sums the components and rounds down to the nearest 5. Missing public purchase or supplier data does not negate evidenced technical fit. Company scale and throughput affect `consumption_intensity`; evidenced control of consumption, supply, resale, installation materials, or specifications affects `company_role_fit` and commercial priority. Keep access, geography, and supplier secrecy outside the score.

In the same assessment call, also assign `product_match` and `commercial_match` as independent 0–10 integers, plus `follow_up` (`跟进` or `淘汰`) and a short rationale. Product match measures supported process/catalog fit without sales access. Commercial match measures the current transaction/cooperation route, throughput, recurrence, role, and purchase/resale/supply/specification control; technical possibility alone is insufficient. Normally both scores are at least 5 for follow-up. A score of 4 may be an explained semantic exception. Neither dimension may compensate for a weak other dimension.

Absence of a public purchase order, named supplier, formulation, furnace model, or exact consumable specification is not evidence of no technical or commercial relevance. When company-specific facts confirm a product family, process, service, or handled-material portfolio, use industrial knowledge to evaluate plausible catalog routes. A technically coherent inference may receive weak or relevant component scores even when the private input is not published; mark the direction `推测`, state the reasoning, and reflect uncertainty in confidence and next questions.

Structured extraction and exact-quote verification improve auditability but do not determine whether a company may be scored. If the retrieved material supports the target company's substantive positioning, assign all five components from that positioning and reasonable industrial inference. Missing direct purchasing evidence or a failed exact-quote extraction lowers confidence and leaves details unresolved; it does not by itself create an abstention or force zero. Preserve the original retrieved evidence for the semantic assessment.

Use three semantic evidence levels, not a keyword or company-type lookup:

- Direct: the company-specific source confirms the input, use, purchase, distribution, specification, or application.
- Strong inference: the company-specific source confirms an output, process, formulation family, service, or handled portfolio for which a catalog route is technically coherent. Score the route according to its specificity and business importance, but keep the unconfirmed detail `推测`.
- Remote adjacency: only a broad industry label or neighboring activity connects the company to the catalog. This alone receives no catalog fit.

A zero score is reserved for cases where the evidence supports no credible direct, strongly inferred, channel, project/specification, complementary-supply, or portfolio-cooperation route after checking the full catalog. Do not use company type as an automatic score, floor, or cap.

Use these anchors consistently:

| Component | None | Weak/remote | Relevant | Strong/core |
|---|---:|---:|---:|---:|
| `production_process_need` | 0 | 8–12 | 18–22 | 25–30 |
| `catalog_fit` | 0 | 8–12 | 18–22 | 25–30 |
| `consumption_intensity` | 0 | 4–7 | 10–14 | 16–20 |
| `demand_recurrence` | 0 | 2–4 | 5–7 | 8–10 |
| `company_role_fit` | 0 | 2–4 | 5–7 | 8–10 |

`company_role_fit` means suitability of the operating role for a catalog-grounded commercial route, not ease of sale. A confirmed refractory manufacturer can be strong/core because it repeatedly consumes raw materials, even when its suppliers, tenders, or willingness to buy from Aceler are not public. A distributor or engineering/specification company can also score across the other four components when its evidenced portfolio reaches relevant applications; its value is not capped at ten points. Being a competitor, an upstream producer, or a large group must not by itself reduce technical or portfolio relevance; express the relationship honestly and put uncertainty about the transaction route in `confidence`, `evidence_status`, and `next_question`.

A confirmed distributor or trader of relevant catalog material is evidence of recurring sourcing and resale even when its current suppliers and future gaps are private. Score its handled applications under `production_process_need`, its product overlap under `catalog_fit`, its handled-market scale under `consumption_intensity`, its repeated trade under `demand_recurrence`, and its market-access role under `company_role_fit`. Do not demand proof of an unmet need, and do not reset these components to zero merely because the company also competes with Aceler.

Apply an internal consistency review before finalizing a low result. Re-evaluate any core refractory manufacturer with several credible catalog mappings that falls below the middle band, and any relevant-material distributor, foundry-consumables formulator, or specification/channel company whose components are all zero. This is a semantic review, not an automatic floor: retain a low result only when the rationale explains why the company-specific facts fail to establish direct, strongly inferred, channel, supply, or portfolio relevance.

Cross-company examples are boundaries, not score templates. A confirmed refractory, foundry, abrasive, ceramic, cement, engineering, distribution, or material-supply activity should be evaluated from the specificity, breadth, intensity, recurrence, and commercial role shown in its own evidence. Do not copy a score from another company or impose a type-based range. Keep genuine exclusions: for example, diamond/CBN/tool-only adjacency does not establish silicon-carbide or fused-alumina use, and an equipment reseller with no relevant application or material influence can still be zero.

### Human-calibrated commercial boundaries

Use the reviewed 100-company human labels to calibrate the meaning of the five components, never as a company-name or memorized-score lookup. Re-research every company and apply these boundaries to its current evidence:

- The total is a practical Aceler commercial-priority score, not the maximum technical plausibility of any product. A technically possible application can support `production_process_need` or `catalog_fit` without automatically creating middle/high overall priority.
- `consumption_intensity` must reflect company-specific indications of industrial material throughput, production capacity, recurring project volume, stocking/distribution scale, or credible fit with Aceler's typical 20–25 MT order size. A small workshop, artisan foundry, retail shop, laboratory, or micro-producer must not receive industrial-scale intensity merely because it uses a technically relevant consumable. Missing scale is unknown rather than zero, but it cannot be assumed strong/core.
- An engineering company or equipment OEM receives channel value across the five components only when company-specific evidence shows relevant material supply, refractory package procurement, formulation, installation-material purchasing, or control of material specifications. Serving steel, cement, glass, foundry, or furnace customers by itself is remote adjacency.
- A distributor or trader must demonstrably handle catalog products, technically substitutable material families, or a clearly relevant refractory/foundry/ceramic/abrasive portfolio. Generic industrial procurement, spare-parts supply, or customer access to relevant industries does not establish a catalog channel.
- A supplier or portfolio partner must manufacture a catalog or genuinely complementary material at commercially meaningful scale and offer a plausible sourcing, representation, or portfolio route for Aceler. Same-industry presence, customer overlap, or a product name alone does not establish that route.
- A high or middle result normally needs a concrete transaction path: meaningful recurring raw-material consumption, relevant formulation/manufacturing, repeated stocking or distribution of mapped materials, project procurement/specification control, or commercially meaningful supply/portfolio overlap. This is a semantic sufficiency test, not a fixed floor, cap, or lookup table.
- Keep access difficulty, incumbent suppliers, qualification, and tender barriers in `entry_barrier`; however, business size and material throughput belong in `consumption_intensity`, and whether the company actually controls a relevant transaction belongs in `company_role_fit`.
- If the exact entity or its core business cannot be established, mark identity/research partial or ambiguous rather than assigning a confident zero or borrowing facts from a namesake.

- `高`: 80–100
- `中`: 55–79
- `低`: 0–54

Set `confidence` independently:

- `高`: entity and core process/business are supported by strong primary evidence.
- `中`: core classification is supported but purchase behavior or application has gaps.
- `低`: identity, process, or buyer/channel control rests mainly on secondary evidence.

Set `entry_barrier` independently. For large groups, inspect supplier registration, group/regional/local purchasing, compliance onboarding, quality/technical certification, sample testing, plant trials, approved-vendor lists, incumbent contracts, and whether an EPC/OEM/contractor controls specification or purchase.

## Structured assessment schema

Prepare a UTF-8 JSON file in this shape before writing the final answer:

```json
{
  "company": "Example Steel Co.",
  "identity_status": "confirmed",
  "research_status": "complete",
  "company_positioning": {
    "text": "Operates an EAF steelmaking plant and rolling mill.",
    "evidence_ids": ["S1"]
  },
  "role_judgment": {
    "operational_role": "终端用户",
    "commercial_relationship": "潜在客户",
    "secondary_relationship": "",
    "reason": "Consumes furnace and ladle refractories.",
    "evidence_ids": ["S1"]
  },
  "match": {
    "product_match": 9,
    "commercial_match": 7,
    "follow_up": "跟进",
    "decision_rationale": "The confirmed EAF operation creates direct catalog demand at industrial scale and a recurring plant-level procurement route.",
    "components": {
      "production_process_need": 28,
      "catalog_fit": 26,
      "consumption_intensity": 17,
      "demand_recurrence": 9,
      "company_role_fit": 8
    },
    "only_industry_label": false,
    "relevant_process_or_business_confirmed": true,
    "official_core_evidence": true,
    "sourcing_or_channel_signal_confirmed": true,
    "confidence": "高",
    "entry_barrier": "高",
    "rationale": "Confirmed EAF and recurring refractory applications create strong demand across several Aceler catalog products."
  },
  "confirmed_processes": ["EAF", "LF", "continuous casting"],
  "confirmed_lining_systems": [],
  "procurement_directions": [
    {
      "product": "Graphite Electrode",
      "priority": "高",
      "application": "EAF",
      "evidence_status": "推测",
      "basis": "The company operates EAF steelmaking; the published incumbent specification is unavailable.",
      "evidence_ids": ["S1"],
      "next_question": "Confirm electrode grade, diameter, nipple system, annual tender cycle, and trial requirements."
    }
  ],
  "sources": [
    {
      "id": "S1",
      "title": "Official process page",
      "url": "https://example.com/process",
      "source_type": "官网"
    }
  ]
}
```

Allowed JSON values:

- `identity_status`: `confirmed` or `ambiguous`
- `research_status`: `complete` or `partial`
- `confidence`, `entry_barrier`, `priority`: `高`, `中`, or `低`
- `evidence_status`: `已确认`, `推测`, or `公开资料未确认`

Run `python3 scripts/validate_assessment.py assessment.json`. Use its computed score and level in the report.

The validator hard-checks only structure, allowed values, score ranges, and evidence-reference integrity. Product/process meaning is evaluated from the full evidence by the researcher under this contract; free-text process wording must never become a string-matching rejection gate. Plausibility conflicts may be reported as warnings for review, but do not invalidate an otherwise well-formed assessment.

## Final report template

```markdown
## 公司实质定位

[One compact factual paragraph with inline clickable sources.]

## 角色判断

- 运营角色：[one label]
- 对 Aceler 的关系：[one label; add a secondary relationship only if supported]
- 判断：[one concise reason with source]

## 匹配度

- [高/中/低]（约 [validator score]%）
- 产品匹配：[product_match]/10
- 商业匹配：[commercial_match]/10
- 最终建议：[follow_up]
- 决策依据：[decision_rationale]
- 证据置信度：[高/中/低]
- 进入门槛：[高/中/低]
- 评分依据：[only the five product/process scoring components]

## 主要采购方向

| 优先级 | Aceler 产品 | 对应流程/用途 | 依据状态 | 下一步确认 |
|---|---|---|---|---|
| 高 | ... | ... | 推测 | ... |
```

Do not repeat positioning in `角色判断`, roles in `匹配度`, or the score in `主要采购方向`. If there is no defensible product direction, say so directly instead of filling the table.
