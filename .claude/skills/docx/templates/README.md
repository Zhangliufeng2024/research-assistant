# Engineering Paper Word Templates

## Templates

- `engineering_paper_cn.js` — Chinese engineering journal template (建筑结构学报 style)
- `engineering_paper_en.js` — International engineering journal template (ASCE/Elsevier style)

## Usage

```bash
# Install dependency (one-time)
npm install -g docx

# Generate Chinese template
node .claude/skills/docx/templates/engineering_paper_cn.js output.docx

# Generate English template
node .claude/skills/docx/templates/engineering_paper_en.js output.docx
```

## Features

- Proper heading hierarchy (H1, H2, H3)
- A4 (Chinese) or Letter (US) page size
- Correct fonts (SimSun/SimHei for Chinese, Times New Roman for English)
- Sample tables with headers and formatting
- Page numbers in footer
- Section structure following IMRaD format
- Chinese GB/T 7714 citation format examples
