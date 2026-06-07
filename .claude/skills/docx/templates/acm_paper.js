// ACM Conference/Journal Paper Template
const { convertInchesToTwip } = require('docx');

const ACM_TEMPLATE = {
  name: "ACM Conference Paper",
  description: "ACM SIGCONF format for CS conferences (KDD, SIGMOD, CHI, WWW, etc.)",
  page: {
    size: { width: convertInchesToTwip(8.5), height: convertInchesToTwip(11) },
    margin: { top: convertInchesToTwip(0.75), bottom: convertInchesToTwip(1), left: convertInchesToTwip(0.75), right: convertInchesToTwip(0.75) }
  },
  fonts: {
    title: { name: "Times New Roman", size: 18, bold: true, centered: true },
    author: { name: "Times New Roman", size: 12, centered: true },
    affiliation: { name: "Times New Roman", size: 10, italic: true, centered: true },
    body: { name: "Times New Roman", size: 9 },
    heading1: { name: "Times New Roman", size: 11, bold: true },
    heading2: { name: "Times New Roman", size: 10, bold: true },
    reference: { name: "Times New Roman", size: 8 }
  },
  spacing: { title: { before: 0, after: 120, line: 240 }, body: { before: 0, after: 60, line: 240 }, reference: { before: 0, after: 40, line: 200 } },
  sections: [
    "Abstract", "CCS Concepts", "Keywords",
    "1 Introduction", "2 Related Work", "3 Method",
    "4 Experiments", "5 Discussion", "6 Conclusion",
    "Acknowledgments", "References"
  ],
  reference_style: "ACM",
  citation_format: "[1] A. Author, B. Author, and C. Author. 2024. Title. Proc. ACM Conf. XX, 1 (January 2024), 1-15. https://doi.org/xx.xxx",
  notes: [
    "ACM SIGCONF format (conference proceedings)",
    "CCS Concepts required (https://dl.acm.org/ccs)",
    "9pt body font, two-column format for final version",
    "Anonymous submission for review (remove author info)",
    "References use numbered format [1], [2], etc.",
    "Appendix pages numbered separately"
  ]
};

module.exports = { ACM_TEMPLATE };
