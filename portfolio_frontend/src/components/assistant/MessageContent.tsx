import { Fragment, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

/** Render the assistant's restricted markdown: paragraphs, "-" bullets, numbered lists, bold, code, links. */
export default function MessageContent({ text }: { text: string }) {
  const blocks = splitBlocks(text);
  return (
    <>
      {blocks.map((block, index) => {
        if (block.kind === 'bullets') {
          return <ul key={index}>{block.items.map((item, i) => <li key={i}>{renderInline(item)}</li>)}</ul>;
        }
        if (block.kind === 'numbered') {
          return <ol key={index}>{block.items.map((item, i) => <li key={i}>{renderInline(item)}</li>)}</ol>;
        }
        if (block.kind === 'code') {
          return <pre key={index}><code>{block.text}</code></pre>;
        }
        return <p key={index}>{renderInline(block.text)}</p>;
      })}
    </>
  );
}

type Block =
  | { kind: 'paragraph'; text: string }
  | { kind: 'bullets'; items: string[] }
  | { kind: 'numbered'; items: string[] }
  | { kind: 'code'; text: string };

function splitBlocks(text: string): Block[] {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { kind: 'bullets' | 'numbered'; items: string[] } | null = null;
  let code: string[] | null = null;
  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ kind: 'paragraph', text: paragraph.join(' ') });
    paragraph = [];
  };
  const flushList = () => {
    if (list) blocks.push(list);
    list = null;
  };
  for (const raw of lines) {
    if (code) {
      if (raw.trim().startsWith('```')) { blocks.push({ kind: 'code', text: code.join('\n') }); code = null; }
      else code.push(raw);
      continue;
    }
    const line = raw.replace(/^#{1,6}\s+/, '');
    if (line.trim().startsWith('```')) { flushParagraph(); flushList(); code = []; continue; }
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      flushParagraph();
      const kind = bullet ? 'bullets' : 'numbered';
      if (!list || list.kind !== kind) { flushList(); list = { kind, items: [] }; }
      list.items.push((bullet ?? numbered)![1]);
      continue;
    }
    if (!line.trim()) { flushParagraph(); flushList(); continue; }
    if (list && /^\s{2,}/.test(raw)) { list.items[list.items.length - 1] += ' ' + line.trim(); continue; }
    flushList();
    paragraph.push(line.trim());
  }
  if (code) blocks.push({ kind: 'code', text: (code as string[]).join('\n') });
  flushParagraph();
  flushList();
  return blocks;
}

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|\/analysis\/[0-9a-f-]{36})/g;

function renderInline(text: string): ReactNode {
  const parts = text.split(INLINE);
  return parts.map((part, index) => {
    if (!part) return null;
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>;
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (link) return renderLink(link[2], link[1], index);
    if (part.startsWith('/analysis/')) return renderLink(part, 'Open analysis', index);
    return <Fragment key={index}>{part}</Fragment>;
  });
}

function renderLink(href: string, label: string, key: number): ReactNode {
  if (href.startsWith('/')) return <Link key={key} to={href} className="assistant-link">{label}</Link>;
  if (/^https?:\/\//.test(href)) {
    return <a key={key} href={href} target="_blank" rel="noopener noreferrer" className="assistant-link">{label}</a>;
  }
  return <Fragment key={key}>{label}</Fragment>;
}
