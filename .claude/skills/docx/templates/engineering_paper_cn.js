// Chinese Engineering Journal Paper Template
// Usage: node engineering_paper_cn.js [output_path]
// Generates a .docx template for Chinese engineering journals (建筑结构学报, 土木工程学报, etc.)

const { Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell,
        WidthType, AlignmentType, PageNumber, Footer, Header, TabStopPosition, TabStopType,
        BorderStyle, ShadingType, ImageRun, TableOfContents } = require("docx");
const fs = require("fs");

const outputPath = process.argv[2] || "engineering_paper_cn.docx";

const doc = new Document({
  styles: {
    default: {
      document: {
        run: {
          font: "SimSun",
          size: 24, // 12pt = 24 half-points
        },
      },
      heading1: {
        run: {
          font: "SimHei",
          size: 28, // 14pt
          bold: true,
        },
        paragraph: {
          spacing: { before: 360, after: 200 },
          alignment: AlignmentType.CENTER,
        },
      },
      heading2: {
        run: {
          font: "SimHei",
          size: 24, // 12pt
          bold: true,
        },
        paragraph: {
          spacing: { before: 240, after: 120 },
        },
      },
      heading3: {
        run: {
          font: "SimHei",
          size: 24,
          bold: true,
        },
        paragraph: {
          spacing: { before: 200, after: 100 },
        },
      },
    },
  },
  sections: [
    {
      properties: {
        page: {
          size: {
            width: 11906, // A4 width in DXA
            height: 16838, // A4 height in DXA
          },
          margin: {
            top: 1440, // 2.54cm = 1 inch
            bottom: 1440,
            left: 1440,
            right: 1440,
          },
        },
      },
      headers: {
        default: new Header({
          children: [
            new Paragraph({
              children: [
                new TextRun({
                  text: "建筑结构学报",
                  font: "SimSun",
                  size: 18,
                  color: "999999",
                }),
              ],
              alignment: AlignmentType.CENTER,
            }),
          ],
        }),
      },
      footers: {
        default: new Footer({
          children: [
            new Paragraph({
              children: [
                new TextRun({
                  children: [PageNumber.CURRENT],
                  font: "Times New Roman",
                  size: 20,
                }),
              ],
              alignment: AlignmentType.CENTER,
            }),
          ],
        }),
      },
      children: [
        // Title
        new Paragraph({
          children: [
            new TextRun({
              text: "论文标题（宋体，二号，加粗）",
              bold: true,
              font: "SimHei",
              size: 36, // 18pt
            }),
          ],
          alignment: AlignmentType.CENTER,
          spacing: { after: 200 },
        }),
        // Authors
        new Paragraph({
          children: [
            new TextRun({
              text: "作者1¹  作者2²  作者3¹",
              font: "SimSun",
              size: 24,
            }),
          ],
          alignment: AlignmentType.CENTER,
          spacing: { after: 100 },
        }),
        // Affiliations
        new Paragraph({
          children: [
            new TextRun({
              text: "（1. 大学名称 土木工程学院，北京 100084；2. 研究院名称，上海 200092）",
              font: "SimSun",
              size: 20, // 10pt
            }),
          ],
          alignment: AlignmentType.CENTER,
          spacing: { after: 300 },
        }),
        // Abstract
        new Paragraph({
          children: [
            new TextRun({
              text: "摘要：",
              bold: true,
              font: "SimHei",
              size: 24,
            }),
            new TextRun({
              text: "在此输入摘要内容。摘要应概括论文的主要内容，包括研究目的、方法、结果和结论。中文摘要一般200-300字。",
              font: "SimSun",
              size: 24,
            }),
          ],
          spacing: { after: 100 },
        }),
        // Keywords
        new Paragraph({
          children: [
            new TextRun({
              text: "关键词：",
              bold: true,
              font: "SimHei",
              size: 24,
            }),
            new TextRun({
              text: "关键词1；关键词2；关键词3；关键词4；关键词5",
              font: "SimSun",
              size: 24,
            }),
          ],
          spacing: { after: 300 },
        }),
        // English Title
        new Paragraph({
          children: [
            new TextRun({
              text: "English Title Here",
              bold: true,
              font: "Times New Roman",
              size: 28,
            }),
          ],
          alignment: AlignmentType.CENTER,
          spacing: { after: 200 },
        }),
        // English Abstract
        new Paragraph({
          children: [
            new TextRun({
              text: "Abstract: ",
              bold: true,
              font: "Times New Roman",
              size: 24,
            }),
            new TextRun({
              text: "Enter English abstract here. The abstract should summarize the purpose, methods, results, and conclusions of the study.",
              font: "Times New Roman",
              size: 24,
            }),
          ],
          spacing: { after: 100 },
        }),
        // English Keywords
        new Paragraph({
          children: [
            new TextRun({
              text: "Keywords: ",
              bold: true,
              font: "Times New Roman",
              size: 24,
            }),
            new TextRun({
              text: "keyword1; keyword2; keyword3; keyword4; keyword5",
              font: "Times New Roman",
              size: 24,
            }),
          ],
          spacing: { after: 400 },
        }),
        // Introduction
        new Paragraph({
          text: "1  引言",
          heading: HeadingLevel.HEADING_1,
        }),
        new Paragraph({
          children: [
            new TextRun({
              text: "在此输入引言内容。引言应介绍研究背景、国内外研究现状、研究目的和意义。",
              font: "SimSun",
              size: 24,
            }),
          ],
          spacing: { after: 200 },
          indent: { firstLine: 480 },
        }),
        // Methodology
        new Paragraph({
          text: "2  试验概况",
          heading: HeadingLevel.HEADING_1,
        }),
        new Paragraph({
          text: "2.1  试件设计",
          heading: HeadingLevel.HEADING_2,
        }),
        new Paragraph({
          children: [
            new TextRun({
              text: "在此描述试件设计，包括几何尺寸、材料参数、设计依据（如GB 50010-2010、GB 50011-2010等）。",
              font: "SimSun",
              size: 24,
            }),
          ],
          spacing: { after: 200 },
          indent: { firstLine: 480 },
        }),
        // Sample table
        new Paragraph({
          text: "表1  试件参数",
          heading: HeadingLevel.HEADING_3,
          alignment: AlignmentType.CENTER,
        }),
        new Table({
          width: { size: 100, type: WidthType.PERCENTAGE },
          rows: [
            new TableRow({
              children: [
                new TableCell({
                  width: { size: 25, type: WidthType.PERCENTAGE },
                  children: [new Paragraph({ children: [new TextRun({ text: "试件编号", bold: true, font: "SimSun", size: 20 })], alignment: AlignmentType.CENTER })],
                  shading: { type: ShadingType.CLEAR, fill: "E8E8E8" },
                }),
                new TableCell({
                  width: { size: 25, type: WidthType.PERCENTAGE },
                  children: [new Paragraph({ children: [new TextRun({ text: "截面尺寸/mm", bold: true, font: "SimSun", size: 20 })], alignment: AlignmentType.CENTER })],
                  shading: { type: ShadingType.CLEAR, fill: "E8E8E8" },
                }),
                new TableCell({
                  width: { size: 25, type: WidthType.PERCENTAGE },
                  children: [new Paragraph({ children: [new TextRun({ text: "钢材等级", bold: true, font: "SimSun", size: 20 })], alignment: AlignmentType.CENTER })],
                  shading: { type: ShadingType.CLEAR, fill: "E8E8E8" },
                }),
                new TableCell({
                  width: { size: 25, type: WidthType.PERCENTAGE },
                  children: [new Paragraph({ children: [new TextRun({ text: "轴压比", bold: true, font: "SimSun", size: 20 })], alignment: AlignmentType.CENTER })],
                  shading: { type: ShadingType.CLEAR, fill: "E8E8E8" },
                }),
              ],
            }),
            new TableRow({
              children: [
                new TableCell({ children: [new Paragraph({ children: [new TextRun({ text: "SC-1", font: "SimSun", size: 20 })], alignment: AlignmentType.CENTER })] }),
                new TableCell({ children: [new Paragraph({ children: [new TextRun({ text: "300×300", font: "SimSun", size: 20 })], alignment: AlignmentType.CENTER })] }),
                new TableCell({ children: [new Paragraph({ children: [new TextRun({ text: "Q345B", font: "SimSun", size: 20 })], alignment: AlignmentType.CENTER })] }),
                new TableCell({ children: [new Paragraph({ children: [new TextRun({ text: "0.3", font: "SimSun", size: 20 })], alignment: AlignmentType.CENTER })] }),
              ],
            }),
            new TableRow({
              children: [
                new TableCell({ children: [new Paragraph({ children: [new TextRun({ text: "SC-2", font: "SimSun", size: 20 })], alignment: AlignmentType.CENTER })] }),
                new TableCell({ children: [new Paragraph({ children: [new TextRun({ text: "300×300", font: "SimSun", size: 20 })], alignment: AlignmentType.CENTER })] }),
                new TableCell({ children: [new Paragraph({ children: [new TextRun({ text: "Q345B", font: "SimSun", size: 20 })], alignment: AlignmentType.CENTER })] }),
                new TableCell({ children: [new Paragraph({ children: [new TextRun({ text: "0.5", font: "SimSun", size: 20 })], alignment: AlignmentType.CENTER })] }),
              ],
            }),
          ],
        }),
        new Paragraph({ text: "", spacing: { after: 200 } }),
        // Results
        new Paragraph({
          text: "3  试验结果及分析",
          heading: HeadingLevel.HEADING_1,
        }),
        new Paragraph({
          children: [
            new TextRun({
              text: "在此输入试验结果和分析内容。应包括荷载-位移曲线、应变分布、破坏模式、延性系数、能量耗散等关键指标。",
              font: "SimSun",
              size: 24,
            }),
          ],
          spacing: { after: 200 },
          indent: { firstLine: 480 },
        }),
        // Conclusions
        new Paragraph({
          text: "4  结论",
          heading: HeadingLevel.HEADING_1,
        }),
        new Paragraph({
          children: [
            new TextRun({
              text: "1) 结论1...",
              font: "SimSun",
              size: 24,
            }),
          ],
          spacing: { after: 100 },
          indent: { firstLine: 480 },
        }),
        new Paragraph({
          children: [
            new TextRun({
              text: "2) 结论2...",
              font: "SimSun",
              size: 24,
            }),
          ],
          spacing: { after: 100 },
          indent: { firstLine: 480 },
        }),
        new Paragraph({
          children: [
            new TextRun({
              text: "3) 结论3...",
              font: "SimSun",
              size: 24,
            }),
          ],
          spacing: { after: 300 },
          indent: { firstLine: 480 },
        }),
        // References
        new Paragraph({
          text: "参考文献",
          heading: HeadingLevel.HEADING_1,
        }),
        new Paragraph({
          children: [
            new TextRun({
              text: "[1] 张三, 李四. 钢结构梁柱节点抗震性能试验研究[J]. 建筑结构学报, 2023, 44(5): 1-12.",
              font: "SimSun",
              size: 20,
            }),
          ],
          spacing: { after: 100 },
        }),
        new Paragraph({
          children: [
            new TextRun({
              text: "[2] SMITH A B, JONES C D. Seismic performance of steel moment connections[J]. Journal of Structural Engineering, 2023, 149(5): 04023045.",
              font: "Times New Roman",
              size: 20,
            }),
          ],
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
