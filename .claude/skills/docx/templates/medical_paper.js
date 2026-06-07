// Medical Journal Word Template (NEJM/Lancet/JAMA)
const { convertInchesToTwip } = require('docx');

const MEDICAL_TEMPLATE = {
  name: "Medical Journal Paper",
  description: "High-impact medical journal format for NEJM, Lancet, JAMA, BMJ",
  page: {
    size: { width: convertInchesToTwip(8.5), height: convertInchesToTwip(11) },
    margin: { top: convertInchesToTwip(1), bottom: convertInchesToTwip(1), left: convertInchesToTwip(1.25), right: convertInchesToTwip(1.25) }
  },
  fonts: {
    title: { name: "Times New Roman", size: 14, bold: true },
    author: { name: "Times New Roman", size: 11 },
    body: { name: "Times New Roman", size: 12 },
    heading1: { name: "Times New Roman", size: 12, bold: true },
    heading2: { name: "Times New Roman", size: 12, bold: true, italic: true },
    reference: { name: "Times New Roman", size: 10 }
  },
  spacing: { title: { before: 0, after: 240, line: 300 }, body: { before: 0, after: 120, line: 360 }, reference: { before: 0, after: 60, line: 240 } },
  sections: [
    "Abstract (Structured: Background, Methods, Results, Conclusions)",
    "Introduction", "Methods", "Results", "Discussion",
    "Conclusions", "References", "Supplementary Appendix",
    "Figure Legends", "Tables"
  ],
  reference_style: "Vancouver (numbered)",
  citation_format: "[1] Author AB, Author CD, Author EF. Title. Journal. Year;Volume(Issue):Pages. doi:xxx",
  journal_variants: {
    NEJM: { abstract_words: 250, body_words: 2500, references_limit: 40, structured_abstract: true },
    Lancet: { abstract_words: 300, body_words: 3000, references_limit: 40, structured_abstract: true },
    JAMA: { abstract_words: 350, body_words: 3500, references_limit: 50, structured_abstract: true },
    BMJ: { abstract_words: 300, body_words: 4000, references_limit: 40, structured_abstract: true }
  },
  notes: [
    "Structured abstract required (Background, Methods, Results, Conclusions)",
    "Vancouver numbered citation style",
    "Patient-centered language required",
    "CONSORT/STROBE/PRISMA compliance required as applicable",
    "ICMJE authorship criteria",
    "Conflict of interest disclosure required",
    "Data sharing statement required (NEJM, JAMA)",
    "Trial registration number required for RCTs"
  ]
};

module.exports = { MEDICAL_TEMPLATE };
