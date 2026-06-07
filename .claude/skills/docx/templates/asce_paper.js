// ASCE Journal Paper Template
// Generates Word documents following ASCE journal formatting requirements

const { Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, TabStopPosition, TabStopType, PageNumber, Footer, Header, SectionType, BorderStyle, convertInchesToTwip } = require('docx');

const ASCE_TEMPLATE = {
  name: "ASCE Journal Paper",
  description: "American Society of Civil Engineers journal paper format",
  page: {
    size: { width: convertInchesToTwip(8.5), height: convertInchesToTwip(11) },
    margin: { top: convertInchesToTwip(1), bottom: convertInchesToTwip(1), left: convertInchesToTwip(1.25), right: convertInchesToTwip(1.25) }
  },
  fonts: {
    title: { name: "Times New Roman", size: 14, bold: true },
    author: { name: "Times New Roman", size: 11 },
    body: { name: "Times New Roman", size: 10 },
    heading1: { name: "Times New Roman", size: 11, bold: true, uppercase: true },
    heading2: { name: "Times New Roman", size: 10, bold: true },
    reference: { name: "Times New Roman", size: 9 }
  },
  spacing: {
    title: { before: 0, after: 240, line: 276 },
    body: { before: 0, after: 0, line: 276 },
    reference: { before: 0, after: 120, line: 240 }
  },
  sections: [
    "Abstract",
    "Introduction",
    "Background / Previous Work",
    "Methodology / Research Approach",
    "Results and Discussion",
    "Conclusions",
    "Data Availability Statement",
    "Acknowledgments",
    "References",
    "Appendix"
  ],
  reference_style: "ASCE",
  citation_format: "Author (Year) \"Title.\" Journal, Volume(Issue), Pages. DOI.",
  notes: [
    "Use serial (Oxford) comma",
    "Spell out numbers one through ten",
    "Use numerals for numbers greater than ten",
    "Use SI units first, imperial in parentheses if needed",
    "Figures and tables should be numbered sequentially",
    "All figures must have captions below",
    "All tables must have captions above"
  ]
};

module.exports = { ASCE_TEMPLATE };
