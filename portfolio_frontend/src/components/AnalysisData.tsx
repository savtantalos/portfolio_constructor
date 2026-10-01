import { useEffect, useMemo, useState } from 'react';
import { extractError, getAnalysisData, getAnalysisExport } from '../api/client';
import type { AnalysisDataResponse, AnalysisDataset, AnalysisResponse } from '../api/types';
import { filterDataRows, formatDataCell } from './dataTable';

const categories: AnalysisDataset['category'][] = ['Market data', 'Risk & estimates', 'Portfolios', 'Backtests'];
const pageSize = 25;

function DatasetPreview({ dataset, download, busy }: {
  dataset: AnalysisDataset;
  download: (id: string) => void;
  busy: boolean;
}) {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const rows = useMemo(() => filterDataRows(dataset.rows, query), [dataset.rows, query]);
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const visibleRows = rows.slice(page * pageSize, (page + 1) * pageSize);

  return (
    <section className="dataset-preview" aria-labelledby="dataset-title">
      <div className="data-panel-header">
        <div>
          <span className="data-eyebrow">{dataset.category}</span>
          <h3 id="dataset-title">{dataset.title}</h3>
        </div>
        <button type="button" className="page-btn" disabled={busy} onClick={() => download(dataset.id)}>
          Download CSV
        </button>
      </div>
      <p className="chart-description">{dataset.description}</p>
      <div className="data-table-tools">
        <div>
          <label className="form-label" htmlFor="data-row-search">Filter preview rows</label>
          <input id="data-row-search" className="form-input" type="search" placeholder="Date, ticker, strategy, or value…"
            value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }} />
        </div>
        <span className="page-info">{dataset.rows.length.toLocaleString()} rows · {dataset.columns.length} columns</span>
      </div>
      <p className="data-table-note" id="data-table-note">
        Preview values are rounded; CSV downloads include all rows at full stored precision, regardless of filters.
        Returns and weights are decimals (0.01 = 1%). A dash means unavailable; CSV cells are left blank.
        Hover over a cell to see its full value.
      </p>
      <div className="data-table-scroll" tabIndex={0} role="region" aria-label={`${dataset.title} table`}>
        <table className="data-table" aria-describedby="data-table-note">
          <caption className="sr-only">{dataset.title}</caption>
          <thead>
            <tr>{dataset.columns.map((column, index) => <th key={index} scope="col">{column}</th>)}</tr>
          </thead>
          <tbody>
            {visibleRows.map((row, index) => (
              <tr key={page * pageSize + index}>
                {row.map((value, column) => (
                  <td key={column} title={value === null ? 'Not available' : String(value)}
                    className={typeof value === 'number' ? 'numeric-cell' : undefined}>
                    {formatDataCell(value)}
                  </td>
                ))}
              </tr>
            ))}
            {visibleRows.length === 0 && (
              <tr><td colSpan={dataset.columns.length} className="empty-state">
                {dataset.rows.length ? 'No matching rows. Try another filter.' : 'No results were saved for this dataset. It may have been disabled or omitted; check the analysis warnings.'}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="pagination">
        <button type="button" className="page-btn" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
        <span className="page-info" role="status">
          {rows.length ? `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, rows.length)} of ${rows.length.toLocaleString()}` : '0 rows'}
          {query.trim() && ' matching'}
        </span>
        <button type="button" className="page-btn" disabled={page + 1 >= pageCount} onClick={() => setPage(page + 1)}>Next</button>
      </div>
    </section>
  );
}

export default function AnalysisData({ analysis }: { analysis: AnalysisResponse }) {
  const [data, setData] = useState<AnalysisDataResponse | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [selectedId, setSelectedId] = useState('');
  const [search, setSearch] = useState('');
  const [downloadError, setDownloadError] = useState('');
  const [downloading, setDownloading] = useState<string | null>(null);
  const [downloadStatus, setDownloadStatus] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    getAnalysisData(analysis.id, controller.signal)
      .then((result) => { if (!controller.signal.aborted) setData(result); })
      .catch((err) => { if (!controller.signal.aborted) setError(extractError(err)); });
    return () => controller.abort();
  }, [analysis.id, attempt]);

  const matching = useMemo(() => {
    const query = search.trim().toLowerCase();
    return data?.datasets.filter((dataset) => `${dataset.title} ${dataset.category} ${dataset.description}`.toLowerCase().includes(query)) ?? [];
  }, [data, search]);
  const selected = matching.find((dataset) => dataset.id === selectedId) ?? matching[0];

  async function download(datasetId?: string) {
    if (downloading) return;
    setDownloading(datasetId ?? 'all');
    setDownloadError('');
    setDownloadStatus('Preparing download…');
    try {
      const blob = await getAnalysisExport(analysis.id, datasetId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `analysis-${analysis.id}${datasetId ? `-${datasetId}.csv` : '.zip'}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setDownloadStatus(`${datasetId ? 'CSV' : 'ZIP'} download ready. Check your browser downloads.`);
    } catch (err) {
      setDownloadError(extractError(err));
      setDownloadStatus('');
    } finally {
      setDownloading(null);
    }
  }

  const provenance = analysis.data;

  return (
    <div className="tab-content data-explorer">
      <section className="data-export-banner" aria-labelledby="data-heading">
        <div>
          <span className="data-eyebrow">Saved analysis · no market-data refresh</span>
          <h2 id="data-heading">Explore the numbers behind the analysis</h2>
          <p>From adjusted prices to portfolio decisions. Preview each dataset, take a CSV into your spreadsheet,
            or download the complete research package.</p>
        </div>
        <div className="data-export-action">
          <button type="button" className="submit-btn" disabled={downloading !== null} onClick={() => download()}>
            {downloading === 'all' ? 'Preparing ZIP…' : 'Download all data (.zip)'}
          </button>
          <span>CSV tables + saved JSON + methodology manifest</span>
        </div>
      </section>
      <div className="data-facts">
        <div><span>Source</span><strong>{provenance.provider}</strong></div>
        <div><span>Assets</span><strong>{analysis.request.tickers.length}</strong></div>
        <div><span>Price observations</span><strong>{provenance.price_observations.toLocaleString()}</strong></div>
        <div><span>Return observations</span><strong>{provenance.return_observations.toLocaleString()}</strong></div>
      </div>
      {downloadError && <div className="alert alert-error" role="alert">Download failed: {downloadError} You can retry the download.</div>}
      <p className="data-download-status" role="status">{downloadStatus}</p>
      <details className="data-provenance">
        <summary>Provenance, units &amp; reproducibility</summary>
        <dl>
          <dt>Requested window</dt><dd>{provenance.requested_start} to {provenance.requested_end}</dd>
          <dt>Effective window</dt><dd>{provenance.effective_start} to {provenance.effective_end}</dd>
          <dt>Fetched at</dt><dd>{provenance.fetched_at}</dd>
          <dt>Price convention</dt><dd>{provenance.adjustment} · {provenance.currency}</dd>
          <dt>Analysis</dt><dd>{analysis.id} · Engine v{analysis.engine_version}</dd>
          <dt>Snapshot SHA-256</dt><dd><code>{provenance.snapshot_sha256}</code></dd>
        </dl>
        <p>Daily returns are calculated as adjusted price / previous adjusted price − 1, not downloaded as a separate Yahoo series.
          Only aligned observations retained by the analysis are available, not raw OHLCV or discarded dates.</p>
        {data?.notes.map((note, index) => <p key={index}>{note}</p>)}
        <p>The package includes the saved request, instrument metadata, assumptions, and warnings.
          Market-data licensing still applies to downloaded data.</p>
      </details>
      {error ? (
        <div className="alert alert-error" role="alert">
          <p>Could not load datasets: {error}</p>
          <button type="button" className="page-btn" onClick={() => { setError(''); setAttempt(attempt + 1); }}>Retry loading data</button>
        </div>
      ) : !data ? (
        <div className="loading-spinner" role="status">Loading saved datasets…</div>
      ) : (
        <div className="data-workspace">
          <nav className="dataset-catalog" aria-label="Analysis datasets">
            <label className="form-label" htmlFor="dataset-search">Find a dataset</label>
            <input id="dataset-search" className="form-input" type="search" placeholder="Search datasets…"
              value={search} onChange={(event) => setSearch(event.target.value)} />
            <p className="data-catalog-count">{matching.length} of {data.datasets.length} datasets</p>
            {categories.map((category) => {
              const datasets = matching.filter((dataset) => dataset.category === category);
              if (!datasets.length) return null;
              return (
                <div className="dataset-group" key={category}>
                  <h3>{category}</h3>
                  {datasets.map((dataset) => (
                    <button type="button" key={dataset.id} className={`dataset-choice ${selected?.id === dataset.id ? 'active' : ''}`}
                      aria-current={selected?.id === dataset.id ? 'true' : undefined} onClick={() => setSelectedId(dataset.id)}>
                      <span>{dataset.title}</span><small>{dataset.rows.length.toLocaleString()} × {dataset.columns.length}</small>
                    </button>
                  ))}
                </div>
              );
            })}
          </nav>
          {selected ? (
            <DatasetPreview key={selected.id} dataset={selected} download={download} busy={downloading !== null} />
          ) : <div className="empty-state">No datasets match your search.</div>}
        </div>
      )}
    </div>
  );
}
