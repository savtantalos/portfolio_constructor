import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { useColorTheme } from './hooks/useColorTheme';
import Sidebar from './components/layout/Sidebar';
import NewAnalysis from './pages/NewAnalysis';
import AnalysisView from './pages/AnalysisView';
import History from './pages/History';

export default function App() {
  const { theme, themeName, setTheme, themeNames } = useColorTheme();

  return (
    <BrowserRouter>
      <div className="app-layout">
        <Sidebar />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<NewAnalysis />} />
            <Route path="/analysis/:id/edit" element={<NewAnalysis />} />
            <Route
              path="/analysis/:id"
              element={
                <AnalysisView
                  theme={theme}
                  themeName={themeName}
                  themeNames={themeNames}
                  setTheme={setTheme}
                />
              }
            />
            <Route path="/history" element={<History />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
