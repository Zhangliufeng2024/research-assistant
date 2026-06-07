// Applied Energy / Energy and Buildings Word Template
const { convertInchesToTwip } = require('docx');

const ENERGY_TEMPLATE = {
  name: "Applied Energy / Energy and Buildings",
  description: "Elsevier energy journal format for Applied Energy, Energy and Buildings, Building and Environment",
  page: {
    size: { width: convertInchesToTwip(8.5), height: convertInchesToTwip(11) },
    margin: { top: convertInchesToTwip(1), bottom: convertInchesToTwip(1), left: convertInchesToTwip(1.25), right: convertInchesToTwip(1.25) }
  },
  fonts: {
    title: { name: "Times New Roman", size: 14, bold: true },
    author: { name: "Times New Roman", size: 11 },
    body: { name: "Times New Roman", size: 10 },
    heading1: { name: "Times New Roman", size: 11, bold: true },
    heading2: { name: "Times New Roman", size: 10, bold: true, italic: true },
    reference: { name: "Times New Roman", size: 9 }
  },
  spacing: { title: { before: 0, after: 240, line: 300 }, body: { before: 0, after: 120, line: 300 }, reference: { before: 0, after: 60, line: 240 } },
  sections: [
    "Highlights", "Abstract", "Keywords", "Nomenclature",
    "1. Introduction", "2. Methodology", "3. Case Study / Results",
    "4. Discussion", "5. Conclusions",
    "CRediT Author Statement", "Declaration of Competing Interest",
    "Acknowledgments", "References", "Appendix"
  ],
  reference_style: "Elsevier Harvard (numbered)",
  domain_specific: {
    required_metrics: ["EUI (kWh/m2/yr)", "Peak load (W/m2)", "COP/EER/SEER", "PMV/PPD", "CO2 concentration"],
    lca_fields: ["Functional unit", "System boundary", "Allocation method", "Data source (ecoinvent version)", "GWP horizon (AR5/AR6)"],
    calibration: ["CV-RMSE (monthly 15%, hourly 30%)", "NMBE (monthly 5%)", "R2", "ASHRAE Guideline 14 reference"],
    hvac_specs: ["System type", "Capacity", "Control strategy", "Refrigerant type", "GWP of refrigerant"]
  },
  notes: [
    "Highlights required: 3-5 bullet points, max 85 characters each",
    "Nomenclature section for symbols and abbreviations",
    "Include energy performance metrics in results tables",
    "Report LCA with ISO 14040/14044 compliance",
    "CRediT author contributions required",
    "Data availability statement required"
  ]
};

module.exports = { ENERGY_TEMPLATE };
