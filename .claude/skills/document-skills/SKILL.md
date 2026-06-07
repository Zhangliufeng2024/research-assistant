---
name: document-skills
description: "Meta-skill for document manipulation across formats: Word (.docx), PDF, PowerPoint (.pptx), and Excel (.xlsx). Routes to format-specific sub-skills."
allowed-tools: [Read, Write, Edit, Bash]
---

# Document Skills

## Overview

Meta-skill that provides document manipulation capabilities across multiple formats. Each format has a dedicated sub-skill with specialized tools and templates.

## Sub-Skills

| Format | Skill Path | Capabilities |
|--------|-----------|--------------|
| Word (.docx) | `document-skills/docx/SKILL.md` | Create, edit, format professional Word documents |
| PDF | `document-skills/pdf/SKILL.md` | PDF generation, conversion, manipulation |
| PowerPoint (.pptx) | `document-skills/pptx/SKILL.md` | Presentation creation and editing |
| Excel (.xlsx) | `document-skills/xlsx/SKILL.md` | Spreadsheet creation, data manipulation |

## When to Use This Skill

- Creating Word documents for Chinese domestic journals or advisor review
- Converting LaTeX/PDF to Word format
- Generating data tables in Excel
- Creating presentation slides
- Any document format conversion task

## Routing Logic

1. Identify target format from user request
2. Load the appropriate sub-skill
3. Apply format-specific templates and tools

## Integration

This skill is referenced by the main research assistant workflow when the user requests Word output or other non-LaTeX formats. The `docx` sub-skill is the most commonly used for academic writing.
