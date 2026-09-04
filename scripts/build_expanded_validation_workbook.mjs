#!/usr/bin/env node

import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error("usage: build_expanded_validation_workbook.mjs INPUT_JSON OUTPUT_XLSX");
const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();
const summary = workbook.worksheets.add("Summary");
const companies = workbook.worksheets.add("Companies");
const thresholds = workbook.worksheets.add("Thresholds");

const navy = "#17365D";
const blue = "#D9EAF7";
const green = "#E2F0D9";
const red = "#FCE4D6";
const gray = "#E7E6E6";
const gold = "#FFF2CC";

summary.showGridLines = false;
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["100 家公司扩大验证"]];
summary.getRange("A1:H1").format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 18 }, rowHeight: 32 };
summary.getRange("A3:B8").values = [
  ["测试口径", "数值"],
  ["阈值", 55],
  ["并发", data.workers],
  ["公司数", data.companies],
  ["人工正样本", data.manual_positive],
  ["人工负样本", data.manual_negative],
];
summary.getRange("D3:H3").values = [["版本", "覆盖率", "精确率", "端到端召回率", "端到端准确率"]];
summary.getRange("D4:D5").values = [["旧版"], ["新版"]];
summary.getRange("E4:H4").formulas = [[
  "=COUNT('Companies'!F2:F101)/'Summary'!$B$6",
  "=IFERROR(COUNTIF('Companies'!H2:H101,\"TP\")/(COUNTIF('Companies'!H2:H101,\"TP\")+COUNTIF('Companies'!H2:H101,\"FP\")),0)",
  "=COUNTIF('Companies'!H2:H101,\"TP\")/'Summary'!$B$7",
  "=(COUNTIF('Companies'!H2:H101,\"TP\")+COUNTIF('Companies'!H2:H101,\"TN\"))/'Summary'!$B$6",
]];
summary.getRange("E5:H5").formulas = [[
  "=COUNT('Companies'!G2:G101)/'Summary'!$B$6",
  "=IFERROR(COUNTIF('Companies'!I2:I101,\"TP\")/(COUNTIF('Companies'!I2:I101,\"TP\")+COUNTIF('Companies'!I2:I101,\"FP\")),0)",
  "=COUNTIF('Companies'!I2:I101,\"TP\")/'Summary'!$B$7",
  "=(COUNTIF('Companies'!I2:I101,\"TP\")+COUNTIF('Companies'!I2:I101,\"TN\"))/'Summary'!$B$6",
]];
summary.getRange("D7:H7").values = [["版本", "TP", "FP", "FN", "不可评分"]];
summary.getRange("D8:D9").values = [["旧版"], ["新版"]];
summary.getRange("E8:H8").formulas = [[
  "=COUNTIF('Companies'!H2:H101,\"TP\")",
  "=COUNTIF('Companies'!H2:H101,\"FP\")",
  "=COUNTIF('Companies'!H2:H101,\"FN\")",
  "=COUNTIF('Companies'!H2:H101,\"ABSTAIN+\")+COUNTIF('Companies'!H2:H101,\"ABSTAIN-\")",
]];
summary.getRange("E9:H9").formulas = [[
  "=COUNTIF('Companies'!I2:I101,\"TP\")",
  "=COUNTIF('Companies'!I2:I101,\"FP\")",
  "=COUNTIF('Companies'!I2:I101,\"FN\")",
  "=COUNTIF('Companies'!I2:I101,\"ABSTAIN+\")+COUNTIF('Companies'!I2:I101,\"ABSTAIN-\")",
]];
summary.getRange("A11:B16").values = [
  ["新版诊断", "结果"],
  ["检索失败", data.failure_stages.retrieval || 0],
  ["结构化失败", data.failure_stages.structured_extraction || 0],
  ["评分失败", data.failure_stages.scoring || 0],
  ["官网域名页占比", data.retrieval.official_domain_page_rate],
  ["合并运行分钟", data.combined_seconds / 60],
];
summary.getRange("D11:E15").values = [
  ["阈值建议", "结果"],
  ["当前阈值", 55],
  ["平衡准确率最优阈值", data.best_threshold_by_balanced_accuracy.threshold],
  ["55 线平衡准确率", data.candidate_at_55.balanced_accuracy_end_to_end],
  ["最优平衡准确率", data.best_threshold_by_balanced_accuracy.balanced_accuracy_end_to_end],
];
summary.getRange("A18:H20").merge(true);
summary.getRange("A18").values = [["结论"]];
summary.getRange("A19").values = [["新版在 55 线的覆盖、召回和准确率均低于旧版；主要问题是检索覆盖下降，同时工程/服务邻接被过度评分。单纯调阈值无法修复不可评分与高价值零分。"]];
summary.getRange("A20").values = [["65 分在本样本上平衡准确率最高，但端到端召回更低；在修复检索与角色边界前，不建议把阈值调整视为主要修复。"]];

for (const range of ["A3:B3", "D3:H3", "D7:H7", "A11:B11", "D11:E11"]) {
  summary.getRange(range).format = { fill: blue, font: { bold: true, color: navy }, borders: { preset: "outside", style: "thin", color: "#A6A6A6" } };
}
summary.getRange("E4:H5").format.numberFormat = "0.0%";
summary.getRange("B15").format.numberFormat = "0.0%";
summary.getRange("B16").format.numberFormat = "0.0";
summary.getRange("E14:E15").format.numberFormat = "0.0%";
summary.getRange("A18:H20").format.wrapText = true;
summary.getRange("A19:H20").format.fill = gold;
summary.getRange("A1:H20").format.font = { name: "Aptos", size: 11 };
summary.getRange("A1:H1").format.font = { name: "Aptos Display", size: 18, bold: true, color: "#FFFFFF" };
summary.getRange("A:H").format.columnWidth = 17;
summary.getRange("A:A").format.columnWidth = 20;
summary.getRange("D:D").format.columnWidth = 22;
summary.getRange("A19:H20").format.rowHeight = 34;

const companyHeaders = [["序号", "人工公司名", "运行公司名", "人工分", "人工标签", "旧版分", "新版分", "旧版判断", "新版判断", "失败阶段", "新版-人工", "运营角色", "商业关系", "置信度", "进入门槛", "证据链接"]];
companies.getRange("A1:P1").values = companyHeaders;
const companyValues = data.rows.map((row) => [
  row.index, row.manual_name, row.input_name, row.manual_score, row.manual_label,
  row.baseline_score, row.candidate_score, null, null, row.failure_stage, null,
  row.operational_role, row.commercial_relationship, row.confidence, row.entry_barrier,
  (row.selected_urls || []).join("\n"),
]);
companies.getRange("A2:P101").values = companyValues;
companies.getRange("H2").formulas = [["=IF(ISBLANK(F2),IF(E2=\"positive\",\"ABSTAIN+\",\"ABSTAIN-\"),IF(AND(E2=\"positive\",F2>='Summary'!$B$4),\"TP\",IF(AND(E2=\"negative\",F2>='Summary'!$B$4),\"FP\",IF(E2=\"positive\",\"FN\",\"TN\"))))"]];
companies.getRange("H2:H101").fillDown();
companies.getRange("I2").formulas = [["=IF(ISBLANK(G2),IF(E2=\"positive\",\"ABSTAIN+\",\"ABSTAIN-\"),IF(AND(E2=\"positive\",G2>='Summary'!$B$4),\"TP\",IF(AND(E2=\"negative\",G2>='Summary'!$B$4),\"FP\",IF(E2=\"positive\",\"FN\",\"TN\"))))"]];
companies.getRange("I2:I101").fillDown();
companies.getRange("K2").formulas = [["=IF(ISBLANK(G2),\"\",G2-D2)"]];
companies.getRange("K2:K101").fillDown();
companies.getRange("A1:P1").format = { fill: navy, font: { bold: true, color: "#FFFFFF" }, rowHeight: 28 };
companies.getRange("A2:P101").format.font = { name: "Aptos", size: 10 };
companies.getRange("A2:P101").format.borders = { insideHorizontal: { style: "thin", color: "#E7E6E6" } };
companies.getRange("B2:C101").format.wrapText = true;
companies.getRange("P2:P101").format.wrapText = true;
companies.getRange("A:A").format.columnWidth = 8;
companies.getRange("B:C").format.columnWidth = 28;
companies.getRange("D:K").format.columnWidth = 12;
companies.getRange("E:E").format.columnWidth = 14;
companies.getRange("H:I").format.columnWidth = 14;
companies.getRange("J:J").format.columnWidth = 22;
companies.getRange("K:K").format.columnWidth = 14;
companies.getRange("L:O").format.columnWidth = 18;
companies.getRange("P:P").format.columnWidth = 42;
companies.getRange("D2:G101").format.numberFormat = "0";
companies.freezePanes.freezeRows(1);
companies.freezePanes.freezeColumns(1);
companies.tables.add("A1:P101", true, "CompaniesTable");
companies.getRange("I2:I101").conditionalFormats.add("containsText", { text: "TP", format: { fill: green, font: { color: "#006100" } } });
companies.getRange("I2:I101").conditionalFormats.add("containsText", { text: "FP", format: { fill: red, font: { color: "#9C0006" } } });
companies.getRange("I2:I101").conditionalFormats.add("containsText", { text: "FN", format: { fill: gold, font: { color: "#9C6500" } } });
companies.getRange("I2:I101").conditionalFormats.add("containsText", { text: "ABSTAIN", format: { fill: gray, font: { color: "#595959" } } });

thresholds.getRange("A1:K1").values = [["阈值", "TP", "FP", "TN", "FN", "正样本不可评分", "负样本不可评分", "精确率", "端到端召回率", "端到端准确率", "平衡准确率"]];
thresholds.getRange("A2:K22").values = data.threshold_scan.map((row) => [
  row.threshold, row.tp, row.fp, row.tn, row.fn, row.abstain_positive, row.abstain_negative,
  row.precision, row.recall_end_to_end, row.accuracy_end_to_end, row.balanced_accuracy_end_to_end,
]);
thresholds.getRange("A1:K1").format = { fill: navy, font: { bold: true, color: "#FFFFFF" }, rowHeight: 28 };
thresholds.getRange("A2:K22").format.borders = { insideHorizontal: { style: "thin", color: "#E7E6E6" } };
thresholds.getRange("H2:K22").format.numberFormat = "0.0%";
thresholds.getRange("A:K").format.columnWidth = 14;
thresholds.getRange("F:G").format.columnWidth = 18;
thresholds.freezePanes.freezeRows(1);
thresholds.tables.add("A1:K22", true, "ThresholdTable");
const chart = thresholds.charts.add("line", { chartType: "line", title: "阈值变化：精确率、召回率与平衡准确率", hasLegend: true });
chart.title = "阈值变化：精确率、召回率与平衡准确率";
chart.hasLegend = true;
for (const [name, column, color] of [["精确率", "H", "#4472C4"], ["端到端召回率", "I", "#70AD47"], ["平衡准确率", "K", "#ED7D31"]]) {
  const series = chart.series.add(name);
  series.categoryFormula = "'Thresholds'!$A$2:$A$22";
  series.formula = `'Thresholds'!$${column}$2:$${column}$22`;
  series.fill = color;
}
chart.yAxis = { numberFormatCode: "0%", min: 0, max: 1 };
chart.xAxis = { axisType: "textAxis" };
chart.setPosition("M2", "U18");

const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(formulaErrors.ndjson);
for (const [sheetName, range, fileName] of [
  ["Summary", "A1:H20", "preview-summary.png"],
  ["Companies", "A1:P22", "preview-companies.png"],
  ["Thresholds", "A1:U22", "preview-thresholds.png"],
]) {
  const preview = await workbook.render({ sheetName, range, scale: 1.2, format: "png" });
  await fs.writeFile(`${outputPath.slice(0, outputPath.lastIndexOf("/"))}/${fileName}`, new Uint8Array(await preview.arrayBuffer()));
}
await fs.mkdir(outputPath.slice(0, outputPath.lastIndexOf("/")), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log((await workbook.inspect({ kind: "table", range: "Summary!A1:H20", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 8 })).ndjson);
