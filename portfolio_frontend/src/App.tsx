import { useState } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { useColorTheme } from './hooks/useColorTheme';
import Sidebar from './components/layout/Sidebar';
import AssistantDrawer from './components/assistant/AssistantDrawer';
import NewAnalysis from './pages/NewAnalysis';
import AnalysisView from './pages/AnalysisView';
import History from './pages/History';

export default function App() {
  const { theme, themeName, setTheme, themeNames } = useColorTheme();
  const [assistantOpen, setAssistantOpen] = useState(false);

  return (
    <BrowserRouter>
      <div className={`app-layout ${assistantOpen ? 'assistant-open' : ''}`}>
        <Sidebar assistantOpen={assistantOpen} onToggleAssistant={() => setAssistantOpen((open) => !open)} />
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
        <AssistantDrawer open={assistantOpen} onClose={() => setAssistantOpen(false)} />
      </div>
    </BrowserRouter>
  );
}
