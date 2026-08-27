# Research, scoring, and report contract

## Input contract

Only a company name is required. Inputs may come from a spreadsheet, API, manual entry, database, or another business system and may omit website, LinkedIn, country, industry, rating, background, contacts, plant, or registration data. Supplied fields are identity hints to verify, not ground truth. Missing fields mean `unknown`; they are not negative evidence, do not reduce any scoring component, and do not justify a zero score or `其他/公开资料不足` role. Base the entity, operating role, process, and product mapping on the evidence gathered for this run.

## Evidence states

- `已确认`: a current, relevant source directly supports the company-specific claim.
- `推测`: a reasonable process/product inference exists, but the company-specific purchase or application is not published.
- `公开资料未确认`: the required fact was searched for but not established publicly.

Never convert a general industry convention into an `已确认` company purchase. A source proves only what it actually states. A refractory manufacturer's finished product or product-family listing proves its output, not its raw-material input. It can support a technically mapped raw-material direction, but that direction remains `推测` unless the source directly confirms the exact input, purchase, or use.

## Role definitions

### Operational role

- `终端用户`: operates a plant/process that consumes relevant products.
- `耐材生产商`: manufactures refractory shapes, monolithics, precast products, or related formulations.
- `贸易商`: buys/sells commodities or industrial materials, typically transaction-led and without a defined territory/service inventory role.
- `分销商`: resells specified products into an established territory/customer base, often with stock, logistics, technical service, or brand representation.
- `工程公司`: designs, specifies, installs, repairs, commissions, or procures for industrial projects.
- `同行`: substantially overlaps Aceler's supplier/trading scope and is not better described by a more concrete operating role.
- `其他/公开资料不足`: none of the above is supportable.

Decide the operational role in this order: first use evidence to identify the company's main revenue activity. Manufacturing refractory bricks, monolithics, precast products, or refractory formulations means `耐材生产商`; operating a production process that consumes relevant products means `终端用户`; designing, specifying, installing, repairing, commissioning, or procuring industrial projects means `工程公司`; reselling with an established territory, inventory, logistics, technical service, or brand representation means `分销商`; general material buying/selling means `贸易商`. Use `同行` only when the main supply scope overlaps Aceler's and no more specific operating role applies; use `其他/公开资料不足` only when evidence supports no specific role. `supplier`, `complete supplier`, `partner`, and `representative` do not by themselves prove manufacturing, and an equipment OEM is not `其他/公开资料不足` merely because it does not buy raw materials. `role_judgment.reason` must name the evidence-supported action (manufactures, resells, designs, installs, or operates), not only an industry label. Judge the commercial relationship to Aceler independently; it must not change the operational role, and a concrete operating role takes priority over `同行` or `其他/公开资料不足`.

A manufacturer of grinding wheels, cutting discs, coated abrasives, nonwoven abrasives, or polishing media is a `终端用户` of mapped abrasive grains. Do not label it `耐材生产商` unless it also manufactures refractory shapes, monolithics, precast refractory products, or refractory formulations.

### Commercial relationship to Aceler

- `潜在客户`: credible direct purchase/consumption or raw-material sourcing opportunity.
- `渠道合作伙伴`: credible resale, specification, project, installation, or customer-access opportunity.
- `同行`: primarily competes or overlaps, with no stronger supported buyer/channel route.
- `低匹配客户`: no meaningful process, product, or channel route is evidenced.

## Score rubric

Score the product and process fit with five integer components:

- `production_process_need` — 0–30: strength of the confirmed production process or application need.
- `catalog_fit` — 0–30: number and specificity of Aceler catalog products that technically map to it.
- `consumption_intensity` — 0–20: likely material intensity of the relevant process or application.
- `demand_recurrence` — 0–10: likelihood of recurring consumption rather than a one-off or remote possibility.
- `company_role_fit` — 0–10: fit between the company's operating role and a product-led Aceler route.

The validator sums the components and rounds down to the nearest 5 to avoid false precision. Procurement evidence, supplier status, certification, access, geography, and source count do not change this score; keep them in confidence, research status, entry barrier, evidence status, or next question.

Absence of a public purchase order, named supplier, formulation, furnace model, or exact consumable specification is not evidence of no technical need. When the company-specific operation is confirmed but these details are unavailable, score the evidenced process/channel fit and mark the product direction `推测` or `公开资料未确认`. A zero score is reserved for cases where the evidence supports no credible catalog product, process, or technical channel route after checking the full catalog.

Use these anchors consistently:

| Component | None | Weak/remote | Relevant | Strong/core |
|---|---:|---:|---:|---:|
| `production_process_need` | 0 | 8–12 | 18–22 | 25–30 |
| `catalog_fit` | 0 | 8–12 | 18–22 | 25–30 |
| `consumption_intensity` | 0 | 4–7 | 10–14 | 16–20 |
| `demand_recurrence` | 0 | 2–4 | 5–7 | 8–10 |
| `company_role_fit` | 0 | 2–4 | 5–7 | 8–10 |

`company_role_fit` means suitability of the operating role for a product-led route, not ease of sale. A confirmed refractory manufacturer can be strong/core because it repeatedly consumes raw materials, even when its suppliers, tenders, or willingness to buy from Aceler are not public. Being a competitor or a large group must not reduce the product/process score. A broad refractory manufacturer with several direct catalog mappings will normally score high; put uncertainty about actual sourcing in `confidence`, `evidence_status`, and `next_question`.

Use these cross-company calibration ranges as consistency checks, not automatic scores:

- A confirmed broad refractory manufacturer with at least three credible catalog mappings will normally fall in `80–95`. Unknown suppliers or competitive overlap do not lower that range.
- A confirmed abrasive manufacturer using at least one mapped abrasive grain will normally fall in `55–75`; evidence of multiple mapped grain families or broad recurring production can support `65–80`. Lack of a public supplier or purchase record does not lower product/process fit.
- Diamond, CBN, tungsten-carbide, superabrasive, or tool-only activity does not establish use of silicon carbide or fused-alumina grains. Without company-specific evidence of a mapped grain or process, treat that adjacency as no catalog fit.
- A confirmed metal foundry with melting and casting operations has non-zero refractory/consumable process fit even when the furnace type, lining chemistry, or purchasing route is unpublished. Keep exact products conditional until their application is evidenced; missing detail changes confidence and next questions, not the existence of the foundry route.
- A confirmed engineering, refractory-service, installation, specification, or material-delivery business has non-zero channel fit when evidence shows it controls or influences relevant materials or projects. An unpublished purchase order changes confidence and evidence status, not `company_role_fit`.
- A confirmed cement plant has non-zero refractory product/process fit even when it buys installed systems through an EPC or maintenance contractor. With only plant-level evidence and no kiln/lining detail, it will normally fall in `25–45`; stronger kiln/application evidence can support a higher score.
- An equipment OEM that neither formulates nor procures relevant materials will normally fall in `0–20`.
- An induction-equipment OEM with an officially confirmed melting application normally has a `20–40` technical/channel fit even when its consumable package and procurement role remain unconfirmed.
- A confirmed generic ready-mix concrete producer without published fiber-reinforced or specialty formulations must total `10–20` through a conditional Steel Fiber route; `4 + 5 + 2 + 2 + 2 = 15` is a suitable five-component baseline. Keep Steel Fiber low priority and `推测`. Only documented specialty-concrete inputs can support a higher score or additional directions; it is not a cement kiln operator.

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
- 证据置信度：[高/中/低]
- 进入门槛：[高/中/低]
- 评分依据：[only the five product/process scoring components]

## 主要采购方向

| 优先级 | Aceler 产品 | 对应流程/用途 | 依据状态 | 下一步确认 |
|---|---|---|---|---|
| 高 | ... | ... | 推测 | ... |
```

Do not repeat positioning in `角色判断`, roles in `匹配度`, or the score in `主要采购方向`. If there is no defensible product direction, say so directly instead of filling the table.
