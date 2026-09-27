import { useMemo, useState } from 'react';
import type { PriceSnapshot } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';
import { calculateAssetStatistics } from './assetStatistics';
import PlotWrapper from './PlotWrapper';

interface Props {
  snapshot: PriceSnapshot;
  theme: ColorTheme;
  currency: string;
}

export default function PriceChart({ snapshot, theme, currency }: Props) {
  const [returnView, setReturnView] = useState<'cumulative' | 'daily'>('cumulative');
  const [window, setWindow] = useState(21);
  const [showPrices, setShowPrices] = useState(false);
  const statistics = useMemo(() => calculateAssetStatistics(snapshot, window), [snapshot, window]);

  if (snapshot.dates.length < 2 || statistics.length === 0) {
    return <div className="empty-state">At least two saved price observations are needed to chart returns.</div>;
  }

  const traces = (metric: 'cumulativeReturns' | 'dailyReturns' | 'rollingVolatility' | 'prices'): Plotly.Data[] => (
    statistics.map((asset, index) => ({
      x: snapshot.dates,
      y: asset[metric],
      mode: 'lines',
      type: 'scatter',
      name: asset.ticker,
      connectgaps: false,
      line: { color: theme.colors[index % theme.colors.length], width: 1.5 },
      hovertemplate: metric === 'prices'
        ? `%{x}<br>%{y:.2f} ${currency}<extra>${asset.ticker}</extra>`
        : `%{x}<br>%{y:.2%}<extra>${asset.ticker}</extra>`,
    }))
  );
  const percentLayout: Partial<Plotly.Layout> = {
    hovermode: 'x unified',
    xaxis: { type: 'date', title: { text: 'Date' }, color: theme.text, gridcolor: theme.gridColor },
    yaxis: { tickformat: '.1%', color: theme.text, gridcolor: theme.gridColor, zerolinecolor: theme.text },
  };
  const hasVolatility = statistics.some((asset) => asset.rollingVolatility.some((value) => value !== null));

  return (
    <div className="asset-charts">
      <p className="page-subtitle">
        Compare individual assets using the saved adjusted prices, not portfolio weights.
        Click a legend entry to hide or show a ticker; double-click to isolate it.
      </p>
      <section className="asset-chart-section" aria-label="Asset returns">
        <div className="chart-controls">
          <label className="form-label" htmlFor="return-view">Return view</label>
          <select id="return-view" className="form-input" value={returnView}
            onChange={(e) => setReturnView(e.target.value as 'cumulative' | 'daily')}>
            <option value="cumulative">Cumulative return</option>
            <option value="daily">Daily return</option>
          </select>
        </div>
        <p className="chart-description">
          {returnView === 'cumulative'
            ? 'Each asset starts at 0%. Return is the adjusted price divided by its first saved price, minus one.'
            : 'Daily return is the percentage change between consecutive saved trading observations.'}
        </p>
        <PlotWrapper
          data={traces(returnView === 'cumulative' ? 'cumulativeReturns' : 'dailyReturns')}
          title={returnView === 'cumulative' ? 'Cumulative Return (%)' : 'Daily Return (%)'}
          theme={theme}
          height={400}
          extraLayout={percentLayout}
        />
      </section>
      <section className="asset-chart-section" aria-label="Asset volatility">
        <div className="chart-controls">
          <label className="form-label" htmlFor="volatility-window">Volatility lookback</label>
          <select id="volatility-window" className="form-input" value={window}
            onChange={(e) => setWindow(Number(e.target.value))}>
            <option value={21}>21 trading days (~1 month)</option>
            <option value={63}>63 trading days (~3 months)</option>
            <option value={126}>126 trading days (~6 months)</option>
            <option value={252}>252 trading days (~1 year)</option>
          </select>
        </div>
        <p className="chart-description">
          Historical volatility: sample standard deviation of the last {window} daily returns,
          annualized using 252 trading days. Higher values mean larger price swings, not higher returns.
          The first {window} price observations have no full return window and are left blank.
        </p>
        {hasVolatility ? (
          <PlotWrapper
            data={traces('rollingVolatility')}
            title={`${window}-Day Rolling Annualized Volatility (%)`}
            theme={theme}
            height={400}
            extraLayout={{ ...percentLayout, yaxis: { ...percentLayout.yaxis, rangemode: 'tozero' } }}
          />
        ) : (
          <div className="empty-state" role="status">
            A {window}-day window needs at least {window + 1} consecutive valid price observations.
            This snapshot has {snapshot.dates.length} observations. Choose a shorter window or rerun with a longer date range.
          </div>
        )}
      </section>
      <button type="button" className="toggle-advanced" aria-expanded={showPrices}
        aria-controls="adjusted-price-chart" onClick={() => setShowPrices(!showPrices)}>
        {showPrices ? 'Hide' : 'Show'} adjusted prices
      </button>
      {showPrices && (
        <div id="adjusted-price-chart">
          <PlotWrapper
            data={traces('prices')}
            title={`Adjusted Closing Prices (${currency})`}
            theme={theme}
            yTitle={`Price (${currency})`}
            height={400}
            extraLayout={{
              xaxis: {
                rangeslider: { visible: true },
                type: 'date',
                color: theme.text,
                gridcolor: theme.gridColor,
              },
            }}
          />
        </div>
      )}
    </div>
  );
}
