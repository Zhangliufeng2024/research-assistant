// International Engineering Journal Paper Template (English)
// Usage: node engineering_paper_en.js [output_path]
// Generates a .docx template for international engineering journals

const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell,
        WidthType, AlignmentType, PageNumber, Footer, Header, BorderStyle, ShadingType } = require("docx");
const fs = require("fs");

const outputPath = process.argv[2] || "engineering_paper_en.docx";

const doc = new Document({
  styles: {
    default: {
      document: {
        run: {
          font: "Times New Roman",
          size: 24, // 12pt
        },
      },
      heading1: {
        run: {
          font: "Times New Roman",
          size: 28,
          bold: true,
        },
        paragraph: {
          spacing: { before: 360, after: 200 },
        },
      },
      heading2: {
        run: {
          font: "Times New Roman",
          size: 24,
          bold: true,
          italics: true,
        },
        paragraph: {
          spacing: { before: 240, after: 120 },
        },
      },
    },
  },
  sections: [
    {
      properties: {
        page: {
          size: {
            width: 12240, // Letter width
            height: 15840, // Letter height
          },
          margin: {
            top: 1440,
            bottom: 1440,
            left: 1440,
            right: 1440,
          },
        },
      },
      footers: {
        default: new Footer({
          children: [
            new Paragraph({
              children: [new TextRun({ children: [PageNumber.CURRENT], size: 20 })],
              alignment: AlignmentType.CENTER,
            }),
          ],
        }),
      },
      children: [
        // Title
        new Paragraph({
          children: [new TextRun({ text: "Paper Title: Subtitle if Any", bold: true, size: 32 })],
          alignment: AlignmentType.CENTER,
          spacing: { after: 300 },
        }),
        // Authors
        new Paragraph({
          children: [new TextRun({ text: "Author Name1, Author Name2, and Author Name3", size: 24 })],
          alignment: AlignmentType.CENTER,
          spacing: { after: 100 },
        }),
        // Affiliations
        new Paragraph({
          children: [new TextRun({ text: "1Department of Civil Engineering, University Name, City, Country", size: 20, italics: true })],
          alignment: AlignmentType.CENTER,
          spacing: { after: 50 },
        }),
        new Paragraph({
          children: [new TextRun({ text: "2Research Institute Name, City, Country", size: 20, italics: true })],
          alignment: AlignmentType.CENTER,
          spacing: { after: 300 },
        }),
        // Abstract
        new Paragraph({
          children: [
            new TextRun({ text: "Abstract", bold: true, size: 24 }),
          ],
          spacing: { after: 100 },
        }),
        new Paragraph({
          children: [
            new TextRun({ text: "Enter abstract here. The abstract should be 150-250 words and summarize the purpose, methods, results, and conclusions of the study.", size: 24 }),
          ],
          spacing: { after: 200 },
        }),
        // Keywords
        new Paragraph({
          children: [
            new TextRun({ text: "Keywords: ", bold: true, size: 24 }),
            new TextRun({ text: "keyword1; keyword2; keyword3; keyword4; keyword5", size: 24 }),
          ],
          spacing: { after: 400 },
        }),
        // 1. Introduction
        new Paragraph({ text: "1. Introduction", heading: HeadingLevel.HEADING_1 }),
        new Paragraph({
          children: [new TextRun({ text: "Enter introduction text here. Provide background, literature review, research gaps, and objectives.", size: 24 })],
          spacing: { after: 200 },
          indent: { firstLine: 480 },
        }),
        // 2. Materials and Methods
        new Paragraph({ text: "2. Materials and Methods", heading: HeadingLevel.HEADING_1 }),
        new Paragraph({ text: "2.1. Specimen Design", heading: HeadingLevel.HEADING_2 }),
        new Paragraph({
          children: [new TextRun({ text: "Describe specimen design, material properties, design codes (e.g., ACI 318-19, AISC 360-22, GB 50011-2010).", size: 24 })],
          spacing: { after: 200 },
          indent: { firstLine: 480 },
        }),
        // Sample table
        new Paragraph({
          children: [new TextRun({ text: "Table 1. Specimen Parameters", bold: true, size: 22 })],
          alignment: AlignmentType.CENTER,
          spacing: { before: 200, after: 100 },
        }),
        new Table({
          width: { size: 100, type: WidthType.PERCENTAGE },
          rows: [
            new TableRow({
              children: [
                new TableCell({
                  width: { size: 25, type: WidthType.PERCENTAGE },
                  children: [new Paragraph({ children: [new TextRun({ text: "Specimen", bold: true, size: 20 })], alignment: AlignmentType.CENTER })],
                  shading: { type: ShadingType.CLEAR, fill: "E8E8E8" },
                }),
                new TableCell({
                  width: { size: 25, type: WidthType.PERCENTAGE },
                  children: [new Paragraph({ children: [new TextRun({ text: "Section (mm)", bold: true, size: 20 })], alignment: AlignmentType.CENTER })],
                  shading: { type: ShadingType.CLEAR, fill: "E8E8E8" },
                }),
                new TableCell({
                  width: { size: 25, type: WidthType.PERCENTAGE },
                  children: [new Paragraph({ children: [new TextRun({ text: "Steel Grade", bold: true, size: 20 })], alignment: AlignmentType.CENTER })],
                  shading: { type: ShadingType.CLEAR, fill: "E8E8E8" },
                }),
                new TableCell({
                  width: { size: 25, type: WidthType.PERCENTAGE },
                  children: [new Paragraph({ children: [new TextRun({ text: "Axial Ratio", bold: true, size: 20 })], alignment: AlignmentType.CENTER })],
                  shading: { type: ShadingType.CLEAR, fill: "E8E8E8" },
                }),
              ],
            }),
            new TableRow({
              children: [
                new TableCell({ children: [new Paragraph({ children: [new TextRun({ text: "SC-1", size: 20 })], alignment: AlignmentType.CENTER })] }),
                new TableCell({ children: [new Paragraph({ children: [new TextRun({ text: "300×300", size: 20 })], alignment: AlignmentType.CENTER })] }),
                new TableCell({ children: [new Paragraph({ children: [new TextRun({ text: "Q345B", size: 20 })], alignment: AlignmentType.CENTER })] }),
                new TableCell({ children: [new Paragraph({ children: [new TextRun({ text: "0.3", size: 20 })], alignment: AlignmentType.CENTER })] }),
              ],
            }),
          ],
        }),
        new Paragraph({ text: "", spacing: { after: 200 } }),
        // 3. Results
        new Paragraph({ text: "3. Results and Discussion", heading: HeadingLevel.HEADING_1 }),
        new Paragraph({
          children: [new TextRun({ text: "Present results including load-displacement curves, strain distributions, failure modes, ductility ratios, and energy dissipation.", size: 24 })],
          spacing: { after: 200 },
          indent: { firstLine: 480 },
        }),
        // 4. Conclusions
        new Paragraph({ text: "4. Conclusions", heading: HeadingLevel.HEADING_1 }),
        new Paragraph({
          children: [new TextRun({ text: "1) Conclusion 1...", size: 24 })],
          spacing: { after: 100 },
          indent: { firstLine: 480 },
        }),
        new Paragraph({
          children: [new TextRun({ text: "2) Conclusion 2...", size: 24 })],
          spacing: { after: 100 },
          indent: { firstLine: 480 },
        }),
        // References
        new Paragraph({ text: "References", heading: HeadingLevel.HEADING_1 }),
        new Paragraph({
          children: [new TextRun({ text: "[1] Smith, A.B., Jones, C.D. (2023). \"Seismic performance of steel moment connections.\" J. Struct. Eng., 149(5), 04023045.", size: 20 })],
          spacing: { after: 100 },
        }),
      ],
    },
  ],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(outputPath, buffer);
  console.log(`Generated: ${outputPath}`);
});
