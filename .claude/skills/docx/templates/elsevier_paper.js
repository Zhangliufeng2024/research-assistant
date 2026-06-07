// Elsevier Journal Paper Template
// Generates Word documents following Elsevier journal formatting requirements

const { Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, TabStopPosition, TabStopType, PageNumber, Footer, Header, SectionType, BorderStyle, convertInchesToTwip } = require('docx');

const ELSEVIER_TEMPLATE = {
  name: "Elsevier Journal Paper",
  description: "Elsevier journal paper format (generic for Engineering journals)",
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
  spacing: {
    title: { before: 0, after: 240, line: 300 },
    body: { before: 0, after: 120, line: 300 },
    reference: { before: 0, after: 60, line: 240 }
  },
  sections: [
    "Highlights",
    "Abstract",
    "Keywords",
    "1. Introduction",
    "2. Materials and Methods",
    "3. Results",
    "4. Discussion",
    "5. Conclusions",
    "CRediT Author Statement",
    "Declaration of Competing Interest",
    "Acknowledgments",
    "References",
    "Appendix A"
  ],
  reference_style: "Elsevier Harvard",
  citation_format: "Author, A.B., Author, C.D., Year. Title. Journal Volume (Issue), Pages. https://doi.org/xxx",
  notes: [
    "Use numbered section headings (1., 1.1., 1.1.1.)",
    "Highlights required: 3-5 bullet points, max 85 characters each",
    "Graphical abstract optional but recommended",
    "CRediT author contributions required",
    "Data availability statement required",
    "Use SI units throughout",
    "References in author-year format (Harvard) or numbered depending on journal"
  ]
};

module.exports = { ELSEVIER_TEMPLATE };
