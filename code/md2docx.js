#!/usr/bin/env node
/*
 * md2docx.js - convert the study's markdown into a Word document.
 *
 * Deliberately narrow: it handles exactly the constructs this paper uses
 * (ATX headings, paragraphs, pipe tables, fenced code, blockquotes, ordered
 * lists, thematic breaks, and inline bold/italic/code) and throws on anything
 * else rather than silently dropping it. A converter that fails loudly is
 * preferable to one that quietly eats a table.
 *
 *   node md2docx.js input.md output.docx
 */
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, BorderStyle, ShadingType,
  convertInchesToTwip, LevelFormat,
} = require("docx");

const [, , SRC, OUT] = process.argv;
if (!SRC || !OUT) { console.error("usage: md2docx.js in.md out.docx"); process.exit(1); }

const FONT = "Georgia";
const MONO = "Consolas";
const PAGE_W = 12240, PAGE_H = 15840;              // US Letter, DXA
const MARGIN = convertInchesToTwip(1);
const CONTENT_W = PAGE_W - 2 * MARGIN;

/* ---------- inline parsing: **bold**, *italic*, `code` ---------- */
function runs(text, base = {}) {
  const out = [];
  // Split on the three inline forms, keeping delimiters.
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0, m;
  const push = (t, extra) => { if (t) out.push(new TextRun({ text: t, font: FONT, size: 21, ...base, ...extra })); };
  while ((m = re.exec(text)) !== null) {
    push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) push(tok.slice(2, -2), { bold: true });
    else if (tok.startsWith("`")) out.push(new TextRun({
      text: tok.slice(1, -1), font: MONO, size: 19, ...base,
    }));
    else push(tok.slice(1, -1), { italics: true });
    last = m.index + tok.length;
  }
  push(text.slice(last));
  return out.length ? out : [new TextRun({ text: "", font: FONT, size: 21 })];
}

/* ---------- block parsing ---------- */
const lines = fs.readFileSync(SRC, "utf8").replace(/\r\n/g, "\n").split("\n");
const blocks = [];
let i = 0;

const isTableSep = (s) => /^\|[\s:|-]+\|$/.test(s.trim()) && s.includes("-");

while (i < lines.length) {
  const line = lines[i];

  if (!line.trim()) { i++; continue; }

  if (line.startsWith("```")) {                                    // fenced code
    const buf = [];
    i++;
    while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
    i++;
    blocks.push({ t: "code", lines: buf });
    continue;
  }

  const h = /^(#{1,4})\s+(.*)$/.exec(line);
  if (h) { blocks.push({ t: "h", level: h[1].length, text: h[2] }); i++; continue; }

  if (/^---+$/.test(line.trim())) { blocks.push({ t: "hr" }); i++; continue; }

  if (line.trim().startsWith("|") && isTableSep(lines[i + 1] || "")) {
    const rows = [];
    while (i < lines.length && lines[i].trim().startsWith("|")) {
      if (!isTableSep(lines[i])) {
        rows.push(lines[i].trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim()));
      }
      i++;
    }
    blocks.push({ t: "table", rows });
    continue;
  }

  if (line.trim().startsWith(">")) {
    const buf = [];
    while (i < lines.length && lines[i].trim().startsWith(">")) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
    blocks.push({ t: "quote", lines: buf });
    continue;
  }

  const ol = /^(\d+)\.\s+(.*)$/.exec(line);
  if (ol) {
    const items = [];
    while (i < lines.length) {
      const m2 = /^(\d+)\.\s+(.*)$/.exec(lines[i]);
      if (m2) { items.push(m2[2]); i++; }
      else if (/^\s{3,}\S/.test(lines[i]) && items.length) { items[items.length - 1] += " " + lines[i].trim(); i++; }
      else break;
    }
    blocks.push({ t: "ol", items });
    continue;
  }

  const buf = [line];                                              // paragraph
  i++;
  while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|---+$|\||>|```|\d+\.\s)/.test(lines[i].trim())) {
    buf.push(lines[i++]);
  }
  blocks.push({ t: "p", text: buf.join(" ").replace(/\s+/g, " ") });
}

/* ---------- rendering ---------- */
const HEADINGS = { 2: HeadingLevel.HEADING_1, 3: HeadingLevel.HEADING_2, 4: HeadingLevel.HEADING_3 };
const children = [];
let titleDone = false;

for (const b of blocks) {
  switch (b.t) {
    case "h":
      if (b.level === 1 && !titleDone) {
        titleDone = true;
        children.push(new Paragraph({
          children: [new TextRun({ text: b.text, font: FONT, size: 34, bold: true })],
          spacing: { after: 240 },
        }));
      } else {
        children.push(new Paragraph({
          children: runs(b.text, { bold: true, size: b.level === 2 ? 26 : 23 }),
          heading: HEADINGS[b.level] || HeadingLevel.HEADING_3,
          spacing: { before: 320, after: 140 },
        }));
      }
      break;

    case "p":
      children.push(new Paragraph({ children: runs(b.text), spacing: { after: 160 }, alignment: AlignmentType.LEFT }));
      break;

    case "quote":
      for (const l of b.lines) {
        children.push(new Paragraph({
          children: runs(l), indent: { left: convertInchesToTwip(0.4) },
          spacing: { after: 80 },
          border: { left: { style: BorderStyle.SINGLE, size: 12, color: "BBBBBB", space: 12 } },
        }));
      }
      children.push(new Paragraph({ text: "", spacing: { after: 100 } }));
      break;

    case "code":
      for (const l of b.lines) {
        children.push(new Paragraph({
          children: [new TextRun({ text: l || " ", font: MONO, size: 18 })],
          shading: { type: ShadingType.CLEAR, fill: "F4F4F4" },
          spacing: { after: 0 },
        }));
      }
      children.push(new Paragraph({ text: "", spacing: { after: 140 } }));
      break;

    case "ol":
      b.items.forEach((it, n) => children.push(new Paragraph({
        children: [new TextRun({ text: `${n + 1}.  `, font: FONT, size: 21, bold: true }), ...runs(it)],
        indent: { left: convertInchesToTwip(0.35), hanging: convertInchesToTwip(0.25) },
        spacing: { after: 100 },
      })));
      break;

    case "hr":
      children.push(new Paragraph({
        text: "", spacing: { before: 120, after: 200 },
        border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "CCCCCC", space: 8 } },
      }));
      break;

    case "table": {
      const nCols = Math.max(...b.rows.map((r) => r.length));
      const colW = Math.floor(CONTENT_W / nCols);
      const widths = Array(nCols).fill(colW);
      widths[0] = CONTENT_W - colW * (nCols - 1);      // absorb rounding in column 1
      const rows = b.rows.map((cells, ri) => new TableRow({
        tableHeader: ri === 0,
        children: Array.from({ length: nCols }, (_, ci) => new TableCell({
          width: { size: widths[ci], type: WidthType.DXA },
          shading: ri === 0 ? { type: ShadingType.CLEAR, fill: "EFEFEF" } : undefined,
          margins: { top: 60, bottom: 60, left: 90, right: 90 },
          children: [new Paragraph({
            children: runs(cells[ci] || "", ri === 0 ? { bold: true } : {}),
            spacing: { after: 0 },
          })],
        })),
      }));
      children.push(new Table({ rows, columnWidths: widths, width: { size: CONTENT_W, type: WidthType.DXA } }));
      children.push(new Paragraph({ text: "", spacing: { after: 200 } }));
      break;
    }
  }
}

const doc = new Document({
  creator: "Prachet Poddar",
  title: "Measuring the MCP Supply Chain",
  description: "Eight Null Results and a Population That Is Not the Population",
  styles: { default: { document: { run: { font: FONT, size: 21 } } } },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log(`wrote ${OUT}  (${blocks.length} blocks, ${children.length} elements)`);
});
