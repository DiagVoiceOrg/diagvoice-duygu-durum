import { useMemo, useState } from 'react';

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function highlightJson(json) {
  return escapeHtml(json).replace(
    /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g,
    (match, str, colon, keyword) => {
      if (colon) {
        return `<span class="usage-json-key">${str}</span>${colon}`;
      }
      if (keyword) {
        return `<span class="usage-json-keyword">${match}</span>`;
      }
      if (str) {
        return `<span class="usage-json-string">${str}</span>`;
      }
      return `<span class="usage-json-number">${match}</span>`;
    },
  );
}

export default function JsonBlock({ value, title, defaultOpen = true, maxHeight = '20rem' }) {
  const [open, setOpen] = useState(defaultOpen);
  const text = useMemo(() => {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }, [value]);

  return (
    <div className="usage-json-block">
      <button type="button" className="usage-json-block-head" onClick={() => setOpen((o) => !o)}>
        <span className="usage-json-block-chevron">{open ? '▾' : '▸'}</span>
        <span>{title || 'JSON'}</span>
        <span className="usage-json-block-meta">{text.split('\n').length} satır</span>
      </button>
      {open ? (
        <pre
          className="usage-json-pre"
          style={{ maxHeight }}
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: highlightJson(text) }}
        />
      ) : null}
    </div>
  );
}
