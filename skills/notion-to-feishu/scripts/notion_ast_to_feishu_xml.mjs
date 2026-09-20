#!/usr/bin/env node

/**
 * Direct Notion AST -> Feishu Docx XML Converter (High-Fidelity)
 *
 * Capabilities:
 * - Direct block tree traversal preserving all nested children
 * - Callouts with emojis and matched color schemes (blue, purple, orange, green, red, yellow, gray)
 * - Deterministic dynamic pastel pills for keywords/code tags
 * - Automatic time badge styling (e.g. 5 分钟 -> purple pill badge)
 * - Multi-column layout (<grid><column width-ratio="...">)
 * - Mermaid diagrams -> <whiteboard type="mermaid">
 * - Interactive collapsible headings & toggles
 * - Tables with <th background-color="light-gray">
 * - Interactive task checkboxes (<checkbox>)
 * - LaTeX math formulas (<latex>)
 * - Images and Bookmarks
 */

const PALETTE = [
  { bg: 'light-blue', text: 'blue' },
  { bg: 'light-purple', text: 'purple' },
  { bg: 'light-green', text: 'green' },
  { bg: 'light-orange', text: 'orange' },
  { bg: 'light-red', text: 'red' },
  { bg: 'light-yellow', text: 'yellow' },
];

function stringHash(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

function escapeXml(unsafe) {
  if (typeof unsafe !== 'string') return '';
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

function mapColor(color) {
  if (!color || color === 'default') return null;
  const c = color.replace('_background', '');
  const valid = ['red', 'orange', 'yellow', 'green', 'blue', 'purple', 'gray'];
  if (valid.includes(c)) return c;
  if (c === 'pink') return 'red';
  if (c === 'brown') return 'orange';
  return 'gray';
}

function formatRichText(richTextArray, options = {}) {
  if (!richTextArray || !richTextArray.length) return '';

  return richTextArray.map((t) => {
    // Handle inline equation
    if (t.type === 'equation' && t.equation?.expression) {
      return `<latex>${escapeXml(t.equation.expression)}</latex>`;
    }

    let text = escapeXml(t.plain_text || t.text?.content || '').replace(/\n/g, '<br/>');
    if (!text) return '';

    const ann = t.annotations || {};

    // Dynamic Colorful keyword pills in keywords callout or tagged code spans
    if (options.isKeywordsCallout && ann.code) {
      const kw = t.plain_text.trim();
      const colorScheme = PALETTE[stringHash(kw) % PALETTE.length];
      return `<span background-color="${colorScheme.bg}" text-color="${colorScheme.text}"><b> ${escapeXml(kw)} </b></span>`;
    }

    // Time badges in headings (e.g. 5 分钟, 8 分钟, 7 分钟)
    if (ann.code && /\d+\s*分钟/.test(t.plain_text)) {
      return `<span background-color="light-purple" text-color="purple"><b> ${escapeXml(t.plain_text.trim())} </b></span>`;
    }

    if (ann.bold) text = `<b>${text}</b>`;
    if (ann.italic) text = `<i>${text}</i>`;
    if (ann.strikethrough) text = `<del>${text}</del>`;
    if (ann.underline) text = `<u>${text}</u>`;
    if (ann.code) text = `<code>${text}</code>`;

    if (ann.color && ann.color !== 'default') {
      const isBg = ann.color.endsWith('_background');
      const base = mapColor(ann.color);
      if (base) {
        if (isBg) {
          text = `<span background-color="light-${base}">${text}</span>`;
        } else {
          text = `<span text-color="${base}">${text}</span>`;
        }
      }
    }

    if (t.href || t.text?.link?.url) {
      const url = escapeXml(t.href || t.text.link.url);
      text = `<a href="${url}">${text}</a>`;
    }

    return text;
  }).join('');
}

function getCalloutColors(iconEmoji, blockColor) {
  let bg = 'light-blue';
  let border = 'blue';

  if (blockColor) {
    const base = mapColor(blockColor);
    if (base) {
      bg = `light-${base}`;
      border = base;
      return { bg, border };
    }
  }

  if (iconEmoji === '🎯') { bg = 'light-blue'; border = 'blue'; }
  else if (iconEmoji === '🔑' || iconEmoji === '📇') { bg = 'light-purple'; border = 'purple'; }
  else if (iconEmoji === '⚠️' || iconEmoji === '🚦') { bg = 'light-orange'; border = 'orange'; }
  else if (iconEmoji === '❌' || iconEmoji === '🚨') { bg = 'light-red'; border = 'red'; }
  else if (iconEmoji === '✅' || iconEmoji === '☑️') { bg = 'light-green'; border = 'green'; }
  else if (iconEmoji === '💡') { bg = 'light-yellow'; border = 'yellow'; }
  else if (iconEmoji === '⏭️' || iconEmoji === '✍️') { bg = 'light-gray'; border = 'gray'; }

  return { bg, border };
}

export function notionAstToFeishuXml(blocks, title = '', options = {}) {
  let xmlParts = [];
  if (title) {
    xmlParts.push(`<title>${escapeXml(title)}</title>`);
  }

  function processBlocks(blockList, depth = 0) {
    let result = [];
    let i = 0;
    while (i < blockList.length) {
      const b = blockList[i];
      const type = b.type;
      const data = b[type];

      switch (type) {
        case 'divider':
          result.push('<hr/>');
          i++;
          break;

        case 'heading_1': {
          const headingText = formatRichText(data.rich_text);
          result.push(`<h1>${headingText}</h1>`);
          if (b.children && b.children.length > 0) {
            result.push(processBlocks(b.children, depth + 1));
          }
          i++;
          break;
        }

        case 'heading_2': {
          const headingText = formatRichText(data.rich_text);
          result.push(`<h2>${headingText}</h2>`);
          if (b.children && b.children.length > 0) {
            result.push(processBlocks(b.children, depth + 1));
          }
          i++;
          break;
        }

        case 'heading_3': {
          const headingText = formatRichText(data.rich_text);
          result.push(`<h3>${headingText}</h3>`);
          if (b.children && b.children.length > 0) {
            result.push(processBlocks(b.children, depth + 1));
          }
          i++;
          break;
        }

        case 'paragraph': {
          const text = formatRichText(data.rich_text);
          if (text.trim()) {
            result.push(`<p>${text}</p>`);
          }
          i++;
          break;
        }

        case 'quote': {
          const text = formatRichText(data.rich_text);
          result.push(`<blockquote><p>${text}</p></blockquote>`);
          i++;
          break;
        }

        case 'callout': {
          const emoji = data.icon?.emoji || '💡';
          const plainTitle = data.rich_text?.map(t => t.plain_text).join('') || '';
          if (/^下一课预告/.test(plainTitle.trim()) && (i > 0 && !String(blockList[i - 1]?.type).startsWith('heading'))) {
            result.push(`<h3>⏭️ 下一课预告</h3>`);
          }
          const isKw = data.rich_text?.some(t => /关键词|Keywords|核心概念|预置词|标签/.test(t.plain_text || ''));
          const colors = getCalloutColors(emoji, data.color);

          let insideBlocks = [];
          let outsideBlocks = [];

          const mainText = formatRichText(data.rich_text, { isKeywordsCallout: isKw });
          if (mainText.trim()) {
            insideBlocks.push(`<p>${mainText}</p>`);
          }

          if (b.children && b.children.length > 0) {
            const allowedTypes = ['paragraph', 'bulleted_list_item', 'numbered_list_item', 'to_do', 'quote', 'code', 'divider', 'table'];
            const insideChildren = [];
            const outsideChildren = [];
            for (const child of b.children) {
              if (allowedTypes.includes(child.type)) {
                insideChildren.push(child);
              } else {
                outsideChildren.push(child);
              }
            }
            if (insideChildren.length > 0) {
              insideBlocks.push(processBlocks(insideChildren, depth + 1));
            }
            if (outsideChildren.length > 0) {
              outsideBlocks.push(processBlocks(outsideChildren, depth));
            }
          }

          result.push(`<callout emoji="${emoji}" background-color="${colors.bg}" border-color="${colors.border}">\n${insideBlocks.join('\n')}\n</callout>`);
          if (outsideBlocks.length > 0) {
            result.push(outsideBlocks.join('\n\n'));
          }
          i++;
          break;
        }

        case 'bulleted_list_item': {
          let listItems = [];
          while (i < blockList.length && blockList[i].type === 'bulleted_list_item') {
            const item = blockList[i];
            let itemText = formatRichText(item.bulleted_list_item.rich_text);
            if (item.children && item.children.length > 0) {
              itemText += `\n${processBlocks(item.children, depth + 1)}`;
            }
            listItems.push(`  <li>${itemText}</li>`);
            i++;
          }
          result.push(`<ul>\n${listItems.join('\n')}\n</ul>`);
          break;
        }

        case 'numbered_list_item': {
          let listItems = [];
          while (i < blockList.length && blockList[i].type === 'numbered_list_item') {
            const item = blockList[i];
            let itemText = formatRichText(item.numbered_list_item.rich_text);
            if (item.children && item.children.length > 0) {
              itemText += `\n${processBlocks(item.children, depth + 1)}`;
            }
            listItems.push(`  <li>${itemText}</li>`);
            i++;
          }
          result.push(`<ol>\n${listItems.join('\n')}\n</ol>`);
          break;
        }

        case 'to_do': {
          const isDone = data.checked ? 'true' : 'false';
          const text = formatRichText(data.rich_text);
          result.push(`<checkbox done="${isDone}">${text}</checkbox>`);
          if (b.children && b.children.length > 0) {
            result.push(processBlocks(b.children, depth + 1));
          }
          i++;
          break;
        }

        case 'toggle': {
          const summary = formatRichText(data.rich_text);
          const isComplex = b.children?.some(c => ['table', 'image', 'column_list', 'callout'].includes(c.type));
          result.push(`<h4>${summary || '折叠内容'}</h4>`);
          if (isComplex && b.children && b.children.length > 0) {
            result.push(processBlocks(b.children, depth + 1));
          }
          i++;
          break;
        }

        case 'code': {
          const codeText = data.rich_text?.map(t => t.plain_text).join('') || '';
          const lang = (data.language || '').toLowerCase();
          const isMermaid = lang === 'mermaid' || /^\s*(flowchart|graph|sequenceDiagram|gantt|classDiagram|stateDiagram|erDiagram|journey|pie)\b/.test(codeText);
          if (isMermaid) {
            result.push(`<whiteboard type="mermaid">\n${codeText.trim()}\n</whiteboard>`);
          } else {
            result.push(`<pre lang="${lang || 'plaintext'}"><code>${escapeXml(codeText)}</code></pre>`);
          }
          i++;
          break;
        }

        case 'column_list': {
          const columns = b.children || [];
          if (columns.length > 0) {
            const numCols = columns.length;
            const standardRatio = Math.floor((1 / numCols) * 100) / 100;
            let colXml = [];
            let totalRatio = 0;
            for (let cIdx = 0; cIdx < numCols; cIdx++) {
              const col = columns[cIdx];
              const isLast = cIdx === numCols - 1;
              const ratio = isLast ? Math.max(0.01, +(1 - totalRatio).toFixed(2)) : standardRatio;
              totalRatio += ratio;
              const colInner = processBlocks(col.children || [], depth + 1);
              colXml.push(`  <column width-ratio="${ratio}">\n${colInner || '<p></p>'}\n  </column>`);
            }
            result.push(`<grid>\n${colXml.join('\n')}\n</grid>`);
          }
          i++;
          break;
        }

        case 'table': {
          const rows = b.children || [];
          if (rows.length > 0) {
            let tableXml = '<table>\n';
            const headerRow = rows[0]?.table_row;
            if (headerRow) {
              tableXml += '  <thead>\n    <tr>\n';
              for (const cell of headerRow.cells) {
                const cellText = formatRichText(cell);
                tableXml += `      <th background-color="light-gray"><p><b>${cellText}</b></p></th>\n`;
              }
              tableXml += '    </tr>\n  </thead>\n';
            }

            if (rows.length > 1) {
              tableXml += '  <tbody>\n';
              for (let r = 1; r < rows.length; r++) {
                const row = rows[r]?.table_row;
                tableXml += '    <tr>\n';
                for (const cell of (row?.cells || [])) {
                  const cellText = formatRichText(cell);
                  tableXml += `      <td><p>${cellText}</p></td>\n`;
                }
                tableXml += '    </tr>\n';
              }
              tableXml += '  </tbody>\n';
            }

            tableXml += '</table>';
            result.push(tableXml);
          }
          i++;
          break;
        }

        case 'image': {
          const caption = data.caption?.map(c => c.plain_text).join('') || '';
          const captionAttr = caption ? ` caption="${escapeXml(caption)}"` : '';
          const localImg = options.imageMap?.get(b.id);
          if (localImg) {
            result.push(`<img path="@./${localImg.fileName}"${captionAttr}/>`);
          } else {
            const url = data.type === 'external' ? data.external?.url : data?.file?.url;
            if (url) {
              result.push(`<img href="${escapeXml(url)}"${captionAttr}/>`);
            }
          }
          i++;
          break;
        }

        case 'bookmark': {
          const bmUrl = data.url || '';
          const bmCaption = data.caption?.map(c => c.plain_text).join('') || bmUrl;
          if (bmUrl) {
            result.push(`<a type="url-preview" href="${escapeXml(bmUrl)}">${escapeXml(bmCaption)}</a>`);
          }
          i++;
          break;
        }

        case 'equation': {
          const expr = data.expression || '';
          if (expr) {
            result.push(`<p><latex>${escapeXml(expr)}</latex></p>`);
          }
          i++;
          break;
        }

        default:
          console.warn(`Unhandled block type: ${type}`);
          i++;
          break;
      }
    }
    return result.join('\n\n');
  }

  xmlParts.push(processBlocks(blocks));
  return xmlParts.join('\n\n');
}

export function extractImagesFromAst(blocks) {
  const images = [];
  function cleanMatchText(str) {
    if (!str) return '';
    const clean = str.replace(/[\r\n\t]+/g, ' ').trim();
    const firstPhrase = clean.split(/[，。！？；\n]/)[0]?.trim();
    return firstPhrase && firstPhrase.length >= 2 ? firstPhrase : clean.slice(0, 15);
  }

  function traverse(list) {
    for (let i = 0; i < list.length; i++) {
      const b = list[i];
      if (b.type === 'image') {
        const data = b.image;
        const url = data?.type === 'external' ? data.external?.url : data?.file?.url;
        const caption = data?.caption?.map(c => c.plain_text).join('') || '';
        let prevText = '';
        let nextText = '';
        if (i > 0) {
          const prev = list[i - 1];
          const prevData = prev[prev.type];
          prevText = prevData?.rich_text?.map(t => t.plain_text).join('') || '';
        }
        if (i + 1 < list.length) {
          const next = list[i + 1];
          const nextData = next[next.type];
          nextText = nextData?.rich_text?.map(t => t.plain_text).join('') || '';
        }
        if (url) {
          images.push({
            id: b.id,
            url,
            caption,
            prevText: cleanMatchText(prevText),
            nextText: cleanMatchText(nextText)
          });
        }
      }
      if (b.children && b.children.length > 0) {
        traverse(b.children);
      }
    }
  }
  traverse(blocks);
  return images;
}

export function extractTogglesFromAst(blocks) {
  const toggles = [];
  function traverse(list) {
    for (let i = 0; i < list.length; i++) {
      const b = list[i];
      if (b.type === 'toggle') {
        const isComplex = b.children?.some(c => ['table', 'image', 'column_list', 'callout'].includes(c.type));
        if (!isComplex) {
          const text = b.toggle?.rich_text?.map(t => t.plain_text).join('').trim() || '';
          toggles.push({
            id: b.id,
            title: text,
            children: b.children || []
          });
        }
      }
      if (b.children && b.children.length > 0) {
        traverse(b.children);
      }
    }
  }
  traverse(blocks);
  return toggles;
}
