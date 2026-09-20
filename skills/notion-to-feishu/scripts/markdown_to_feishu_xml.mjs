#!/usr/bin/env node

/**
 * Transforms Notion-exported Markdown to Feishu Docx XML format.
 * Handles:
 * - Callouts with emoji and matching colors
 * - Mermaid diagrams -> <whiteboard type="mermaid">
 * - Details / Summary toggles -> <h4 folded="true">...</h4>
 * - GFM tables -> <table> with styled light-gray headers
 * - Task lists [ ] -> <checkbox>
 * - Blockquotes -> <blockquote>
 * - Code blocks & inline code
 */

export function markdownToFeishuXml(markdown, title = "") {
  let lines = markdown.split(/\r?\n/);
  let xmlParts = [];
  
  if (title) {
    xmlParts.push(`<title>${escapeXml(title)}</title>`);
  }

  let i = 0;
  while (i < lines.length) {
    let line = lines[i];

    // Blank line
    if (!line.trim()) {
      i++;
      continue;
    }

    // Title / H1 at top (if not already handled)
    if (line.startsWith("# ") && !title) {
      const docTitle = line.replace(/^#\s+/, "").trim();
      xmlParts.unshift(`<title>${escapeXml(docTitle)}</title>`);
      i++;
      continue;
    }

    // Horizontal Rule
    if (/^(\*\*\*|---|___)$/.test(line.trim())) {
      xmlParts.push("<hr/>");
      i++;
      continue;
    }

    // Mermaid Code Block
    if (line.trim().startsWith("```mermaid")) {
      let mermaidCode = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        mermaidCode.push(lines[i]);
        i++;
      }
      i++; // Skip closing ```
      xmlParts.push(`<whiteboard type="mermaid">\n${mermaidCode.join("\n")}\n</whiteboard>`);
      continue;
    }

    // Regular Code Block
    if (line.trim().startsWith("```")) {
      const lang = line.trim().replace(/^```/, "").trim() || "plaintext";
      let codeLines = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // Skip closing ```
      xmlParts.push(`<code language="${lang}">\n${escapeXml(codeLines.join("\n"))}\n</code>`);
      continue;
    }

    // Details / Summary (Toggle Block)
    if (line.trim().startsWith("<details>")) {
      let detailsContent = [];
      i++;
      let summaryText = "";
      while (i < lines.length && !lines[i].trim().startsWith("</details>")) {
        let cur = lines[i];
        if (cur.includes("<summary>")) {
          // Extract summary text
          let sumLines = [];
          while (i < lines.length && !lines[i].includes("</summary>")) {
            sumLines.push(lines[i].replace(/<\/?summary>/g, "").replace(/<\/?strong>/g, "").replace(/<\/?h\d>/g, "").trim());
            i++;
          }
          sumLines.push(lines[i].replace(/<\/?summary>/g, "").replace(/<\/?strong>/g, "").replace(/<\/?h\d>/g, "").trim());
          summaryText = sumLines.join(" ").trim();
          i++;
          continue;
        }
        detailsContent.push(cur);
        i++;
      }
      i++; // Skip </details>

      const innerMd = detailsContent.join("\n").trim();
      const innerXml = markdownToFeishuXml(innerMd);

      xmlParts.push(`<h4>${escapeXml(summaryText || "折叠内容")}\n${innerXml}\n</h4>`);
      continue;
    }

    // Markdown Table
    if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
      let tableRows = [];
      while (i < lines.length && lines[i].trim().startsWith("|") && lines[i].trim().endsWith("|")) {
        tableRows.push(lines[i].trim());
        i++;
      }

      if (tableRows.length >= 2) {
        xmlParts.push(renderTableXml(tableRows));
      }
      continue;
    }

    // Checkbox / Todo item
    if (/^\s*[-*]\s+\[([ xX])\]\s+(.*)$/.test(line)) {
      const match = line.match(/^\s*[-*]\s+\[([ xX])\]\s+(.*)$/);
      const isDone = match[1].toLowerCase() === "x";
      const itemText = formatInline(match[2]);
      xmlParts.push(`<checkbox done="${isDone ? "true" : "false"}">${itemText}</checkbox>`);
      i++;
      continue;
    }

    // Unordered List
    if (/^\s*[-*+]\s+(.*)$/.test(line)) {
      let listItems = [];
      while (i < lines.length && /^\s*[-*+]\s+(.*)$/.test(lines[i]) && !/^\s*[-*]\s+\[([ xX])\]/.test(lines[i])) {
        const itemMatch = lines[i].match(/^\s*[-*+]\s+(.*)$/);
        listItems.push(`  <li>${formatInline(itemMatch[1])}</li>`);
        i++;
      }
      xmlParts.push(`<ul>\n${listItems.join("\n")}\n</ul>`);
      continue;
    }

    // Ordered List
    if (/^\s*\d+\.\s+(.*)$/.test(line)) {
      let listItems = [];
      while (i < lines.length && /^\s*\d+\.\s+(.*)$/.test(lines[i])) {
        const itemMatch = lines[i].match(/^\s*\d+\.\s+(.*)$/);
        listItems.push(`  <li>${formatInline(itemMatch[1])}</li>`);
        i++;
      }
      xmlParts.push(`<ol>\n${listItems.join("\n")}\n</ol>`);
      continue;
    }

    // Blockquote
    if (line.trim().startsWith(">")) {
      let quoteLines = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        quoteLines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      xmlParts.push(`<blockquote>\n  <p>${formatInline(quoteLines.join("<br/>"))}</p>\n</blockquote>`);
      continue;
    }

    // Headings
    if (line.startsWith("### ")) {
      xmlParts.push(`<h3>${formatInline(line.replace(/^###\s+/, ""))}</h3>`);
      i++;
      continue;
    }
    if (line.startsWith("## ")) {
      xmlParts.push(`<h2>${formatInline(line.replace(/^##\s+/, ""))}</h2>`);
      i++;
      continue;
    }
    if (line.startsWith("#### ")) {
      xmlParts.push(`<h4>${formatInline(line.replace(/^####\s+/, ""))}</h4>`);
      i++;
      continue;
    }

    // Notion Callout / HTML aside
    if (line.includes("<aside>") || line.startsWith(":::")) {
      let calloutLines = [];
      i++;
      while (i < lines.length && !lines[i].includes("</aside>") && !lines[i].startsWith(":::")) {
        calloutLines.push(lines[i]);
        i++;
      }
      i++; // Skip closing tag
      xmlParts.push(renderCalloutXml(calloutLines.join("\n")));
      continue;
    }

    // Paragraph
    xmlParts.push(`<p>${formatInline(line)}</p>`);
    i++;
  }

  return xmlParts.join("\n\n");
}

function renderTableXml(rows) {
  const parseRow = (r) => r.split("|").slice(1, -1).map(c => c.trim());
  const headerCells = parseRow(rows[0]);
  
  let xml = "<table>\n  <thead>\n    <tr>\n";
  for (const h of headerCells) {
    xml += `      <th background-color="light-gray"><p>${formatInline(h)}</p></th>\n`;
  }
  xml += "    </tr>\n  </thead>\n  <tbody>\n";

  for (let r = 2; r < rows.length; r++) {
    const cells = parseRow(rows[r]);
    xml += "    <tr>\n";
    for (const c of cells) {
      xml += `      <td><p>${formatInline(c)}</p></td>\n`;
    }
    xml += "    </tr>\n";
  }
  xml += "  </tbody>\n</table>";
  return xml;
}

function renderCalloutXml(content) {
  let emoji = "💡";
  let bg = "light-blue";
  let border = "blue";

  if (content.includes("🎯")) { emoji = "🎯"; bg = "light-blue"; border = "blue"; }
  else if (content.includes("🔑") || content.includes("📇")) { emoji = "🔑"; bg = "light-purple"; border = "purple"; }
  else if (content.includes("⚠️") || content.includes("🚦")) { emoji = "⚠️"; bg = "light-orange"; border = "orange"; }
  else if (content.includes("❌") || content.includes("🚨")) { emoji = "🚨"; bg = "light-red"; border = "red"; }
  else if (content.includes("✅") || content.includes("☑️")) { emoji = "✅"; bg = "light-green"; border = "green"; }
  else if (content.includes("✍️")) { emoji = "✍️"; bg = "light-gray"; border = "gray"; }

  const innerXml = markdownToFeishuXml(content.replace(/^[🎯🔑📇⚠️🚦❌🚨✅☑️✍️💡]\s*/g, ""));
  return `<callout emoji="${emoji}" background-color="${bg}" border-color="${border}">\n${innerXml}\n</callout>`;
}

function escapeXml(unsafe) {
  return unsafe.replace(/[<>&'"]/g, (c) => {
    switch (c) {
      case '<': return '&lt;';
      case '>': return '&gt;';
      case '&': return '&amp;';
      case '\'': return '&apos;';
      case '"': return '&quot;';
      default: return c;
    }
  });
}

function formatInline(text) {
  if (!text) return "";
  let out = text;
  
  // Bold: **text** or __text__
  out = out.replace(/\*\*(.*?)\*\*/g, "<b>$1</b>");
  // Italic: *text* or _text_
  out = out.replace(/(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)/g, "<i>$1</i>");
  // Inline code: `code`
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  // Links: [text](url)
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');

  return out;
}
