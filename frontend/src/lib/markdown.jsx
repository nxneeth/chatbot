// Small, safe markdown renderer for chat replies (no HTML injection).
import React from "react";

function inline(text, keyBase) {
  const parts = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g;
  let last = 0;
  let m;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyBase}-${i++}`;
    if (tok.startsWith("**")) parts.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) parts.push(<code key={key}>{tok.slice(1, -1)}</code>);
    else parts.push(<em key={key}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function isTableRow(line) {
  return /^\s*\|.*\|\s*$/.test(line);
}

export function Markdown({ text }) {
  const lines = (text || "").replace(/\r/g, "").split("\n");
  const blocks = [];
  let i = 0;
  let k = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.trim().startsWith("```")) {
      const code = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) code.push(lines[i++]);
      i++;
      blocks.push(<pre key={k++}><code>{code.join("\n")}</code></pre>);
      continue;
    }
    if (isTableRow(line)) {
      const rows = [];
      while (i < lines.length && isTableRow(lines[i])) rows.push(lines[i++]);
      const cells = rows
        .filter((r) => !/^[\s|:-]+$/.test(r))
        .map((r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
      const [head, ...body] = cells;
      blocks.push(
        <div className="md-table" key={k++}>
          <table>
            <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, `h${j}`)}</th>)}</tr></thead>
            <tbody>{body.map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `c${ri}${j}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      );
      continue;
    }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*•]|\d+[.)])\s+/, ""));
        i++;
      }
      const List = ordered ? "ol" : "ul";
      blocks.push(<List key={k++}>{items.map((it, j) => <li key={j}>{inline(it, `l${k}${j}`)}</li>)}</List>);
      continue;
    }
    if (/^#{1,6}\s+/.test(line)) {
      blocks.push(<h4 key={k++}>{inline(line.replace(/^#{1,6}\s+/, ""), `t${k}`)}</h4>);
      i++;
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !isTableRow(lines[i]) && !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i]) &&
      !lines[i].trim().startsWith("```") && !/^#{1,6}\s+/.test(lines[i])) {
      para.push(lines[i++]);
    }
    blocks.push(
      <p key={k++}>
        {para.map((p, j) => (
          <React.Fragment key={j}>{j > 0 && <br />}{inline(p, `p${k}${j}`)}</React.Fragment>
        ))}
      </p>
    );
  }
  return <>{blocks}</>;
}
