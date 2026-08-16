import { BrowserRouter, Route, Routes } from 'react-router-dom';
import AppLayout from './components/layout/AppLayout';
import ChatPage from './components/chat/ChatPage';
import MemoryPage from './components/memory/MemoryPage';
import SkillsPage from './components/skills/SkillsPage';
import ModelsPage from './components/models/ModelsPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<ChatPage />} />
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="/skills" element={<SkillsPage />} />
          <Route path="/models" element={<ModelsPage />} />
          <Route path="*" element={<ChatPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
