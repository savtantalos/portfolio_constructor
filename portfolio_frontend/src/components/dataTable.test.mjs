import assert from 'node:assert/strict';
import test from 'node:test';
import { filterDataRows, formatDataCell } from './dataTable.ts';

test('preview preserves zeros, missing values, signs, dates, and tiny covariances', () => {
  assert.equal(formatDataCell(null), '—');
  assert.equal(formatDataCell(0), '0');
  assert.equal(formatDataCell(-0), '0');
  assert.equal(formatDataCell(-0.012345678901), '-0.012345679');
  assert.equal(formatDataCell(0.0000000001234), '1.234000e-10');
  assert.equal(formatDataCell(12345678900), '1.234568e+10');
  assert.equal(formatDataCell('2025-01-02'), '2025-01-02');
  assert.equal(formatDataCell('^GSPC'), '^GSPC');
});

test('row search handles dates, strategies, numeric values, and null cells without mutating data', () => {
  const rows = [['2025-01-02', 'AAA', 0, null], ['2025-02-03', 'minimum_variance', -0.123456789, 1]];
  const original = structuredClone(rows);
  assert.equal(filterDataRows(rows, '  '), rows);
  assert.deepEqual(filterDataRows(rows, ' aAa '), [rows[0]]);
  assert.deepEqual(filterDataRows(rows, '2025-02'), [rows[1]]);
  assert.deepEqual(filterDataRows(rows, 'MINIMUM'), [rows[1]]);
  assert.deepEqual(filterDataRows(rows, '-0.123456789'), [rows[1]]);
  assert.deepEqual(filterDataRows(rows, 'null'), []);
  assert.deepEqual(filterDataRows(rows, 'missing'), []);
  assert.deepEqual(filterDataRows([], 'AAA'), []);
  assert.deepEqual(rows, original);
});
