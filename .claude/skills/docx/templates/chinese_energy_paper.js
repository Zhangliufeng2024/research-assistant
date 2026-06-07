// Chinese Energy/HVAC Journal Word Template
const { convertInchesToTwip } = require('docx');

const CHINESE_ENERGY_TEMPLATE = {
  name: "Chinese Energy/HVAC Journal",
  description: "Chinese journal format for 暖通空调, 建筑科学, 建筑节能, 太阳能学报",
  page: {
    size: { width: convertInchesToTwip(8.27), height: convertInchesToTwip(11.69) }, // A4
    margin: { top: convertInchesToTwip(0.98), bottom: convertInchesToTwip(0.98), left: convertInchesToTwip(0.79), right: convertInchesToTwip(0.79) }
  },
  fonts: {
    title: { name: "SimHei", size: 16, bold: true },
    author: { name: "SimSun", size: 10 },
    affiliation: { name: "SimSun", size: 9 },
    body: { name: "SimSun", size: 10 },
    heading1: { name: "SimHei", size: 12, bold: true },
    heading2: { name: "SimHei", size: 11, bold: true },
    reference: { name: "SimSun", size: 9 }
  },
  spacing: { title: { before: 0, after: 200, line: 300 }, body: { before: 0, after: 100, line: 300 }, reference: { before: 0, after: 60, line: 240 } },
  sections: [
    "摘要 (Structured: 目的/方法/结果/结论)",
    "关键词 (3-8个)",
    "0 引言",
    "1 研究方法",
    "2 实测/模拟结果",
    "3 分析与讨论",
    "4 结论",
    "参考文献",
    "英文摘要 (English Abstract)"
  ],
  reference_style: "GB/T 7714-2015",
  citation_format: "[序号] 作者. 题名[文献类型标识]. 刊名, 年, 卷(期): 起止页码.",
  domain_specific: {
    required_metrics: ["EUI (kWh/m2/a)", "冷/热负荷指标 (W/m2)", "COP/EER", "PMV-PPD", "CO2浓度 (ppm)"],
    gb_standards: ["GB 50736 民用建筑供暖通风与空气调节设计规范", "GB 50189 公共建筑节能设计标准", "GB/T 51366 建筑碳排放计算标准"],
    calibration: ["CV(RMSE) 15% (月)", "MBE 5% (月)", "ASHRAE Guideline 14 参考"]
  },
  notes: [
    "A4纸张，宋体10号正文，黑体标题",
    "摘要需结构化：目的、方法、结果、结论",
    "关键词3-8个，中英文对照",
    "参考文献按GB/T 7714-2015格式",
    "需提供英文摘要和英文关键词",
    "图表需中英文对照标题",
    "单位使用国际单位制(SI)"
  ]
};

module.exports = { CHINESE_ENERGY_TEMPLATE };
