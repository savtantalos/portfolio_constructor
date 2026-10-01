import type { AnalysisDataset } from '../api/types';

const numberFormat = new Intl.NumberFormat('en-US', { maximumSignificantDigits: 8, useGrouping: false });

export function formatDataCell(value: string | number | null): string {
  if (value === null) return '—';
  if (typeof value !== 'number') return value;
  if (value === 0) return '0';
  if (Math.abs(value) < 0.000001 || Math.abs(value) >= 1e9) return value.toExponential(6);
  return numberFormat.format(value);
}

export function filterDataRows(rows: AnalysisDataset['rows'], query: string): AnalysisDataset['rows'] {
  const search = query.trim().toLowerCase();
  if (!search) return rows;
  return rows.filter((row) => row.some((value) => value !== null && String(value).toLowerCase().includes(search)));
}
