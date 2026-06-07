// IEEE Conference/Journal Paper Template
// Generates Word documents following IEEE formatting requirements

const { Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, TabStopPosition, TabStopType, PageNumber, Footer, Header, SectionType, BorderStyle, convertInchesToTwip } = require('docx');

const IEEE_TEMPLATE = {
  name: "IEEE Paper",
  description: "IEEE journal/conference paper format (two-column)",
  page: {
    size: { width: convertInchesToTwip(8.5), height: convertInchesToTwip(11) },
    margin: { top: convertInchesToTwip(0.75), bottom: convertInchesToTwip(1), left: convertInchesToTwip(0.625), right: convertInchesToTwip(0.625) },
    columns: 2,
    column_gap: convertInchesToTwip(0.25)
  },
  fonts: {
    title: { name: "Times New Roman", size: 24, bold: true },
    author: { name: "Times New Roman", size: 11 },
    affiliation: { name: "Times New Roman", size: 10, italic: true },
    body: { name: "Times New Roman", size: 10 },
    heading1: { name: "Times New Roman", size: 10, bold: true, uppercase: true, centered: true },
    heading2: { name: "Times New Roman", size: 10, bold: true, italic: true },
    reference: { name: "Times New Roman", size: 8 }
  },
  spacing: {
    title: { before: 0, after: 120, line: 240 },
    body: { before: 0, after: 0, line: 240 },
    reference: { before: 0, after: 40, line: 200 }
  },
  sections: [
    "Abstract",
    "I. Introduction",
    "II. Related Work",
    "III. Methodology",
    "IV. Experiments",
    "V. Results and Discussion",
    "VI. Conclusion",
    "Acknowledgment",
    "References"
  ],
  reference_style: "IEEE",
  citation_format: "[1] A. Author, \"Title,\" Journal, vol. X, no. Y, pp. Z, Month Year, doi: xxx.",
  notes: [
    "Two-column format for IEEE transactions/conferences",
    "Abstract should be 150-250 words",
    "Keywords required after abstract (4-6 keywords)",
    "Roman numeral section headings (I, II, III...)",
    "Equations numbered sequentially in parentheses",
    "Figures and tables referenced as 'Fig. 1' and 'TABLE I'",
    "References numbered in square brackets [1], [2], etc.",
    "Use 'et al.' for more than 3 authors in references"
  ]
};

module.exports = { IEEE_TEMPLATE };
