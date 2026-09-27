import { useState, useRef, useCallback } from 'react';
import { searchAssets, extractError } from '../../api/client';
import type { Instrument } from '../../api/types';

interface Props {
  selected: string[];
  onChange: (tickers: string[]) => void;
  max?: number;
}

export default function TickerSearch({ selected, onChange, max = 30 }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Instrument[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const doSearch = useCallback(async (q: string) => {
    if (q.trim().length < 1) { setResults([]); return; }
    setLoading(true);
    setError('');
    try {
      const items = await searchAssets(q.trim(), 10);
      setResults(items.filter((i) => !selected.includes(i.symbol)));
      setOpen(true);
    } catch (err) {
      setError(extractError(err));
    } finally {
      setLoading(false);
    }
  }, [selected]);

  const handleInput = (value: string) => {
    setQuery(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => doSearch(value), 350);
  };

  const addTicker = (symbol: string) => {
    if (!selected.includes(symbol) && selected.length < max) {
      onChange([...selected, symbol]);
    }
    setQuery('');
    setResults([]);
    setOpen(false);
  };

  const removeTicker = (symbol: string) => {
    onChange(selected.filter((t) => t !== symbol));
  };

  return (
    <div className="ticker-search">
      <label className="form-label">Tickers ({selected.length}/{max})</label>
      <div className="ticker-tags">
        {selected.map((t) => (
          <span key={t} className="ticker-tag">
            {t}
            <button type="button" onClick={() => removeTicker(t)} className="tag-remove" title="Remove" aria-label={`Remove ${t}`}>&times;</button>
          </span>
        ))}
      </div>
      <div className="search-input-wrap">
        <input
          type="text"
          value={query}
          onChange={(e) => handleInput(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 200)}
          placeholder={selected.length >= max ? 'Maximum reached' : 'Search for stocks or ETFs...'}
          disabled={selected.length >= max}
          className="form-input"
        />
        {loading && <span className="search-spinner" />}
      </div>
      {error && <div className="form-error">{error}</div>}
      {open && results.length > 0 && (
        <ul className="search-dropdown">
          {results.map((item) => (
            <li key={item.symbol} onMouseDown={() => addTicker(item.symbol)} className="search-item">
              <strong>{item.symbol}</strong>
              <span className="search-meta">
                {item.name && <span>{item.name}</span>}
                {item.exchange && <span className="search-exchange">{item.exchange}</span>}
                {item.instrument_type && <span className="search-type">{item.instrument_type}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
