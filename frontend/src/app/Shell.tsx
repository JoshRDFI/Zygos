import { Route, Routes } from "react-router-dom";
import Header from "./Header";
import LeftRail from "./LeftRail";
import ContextPanel from "./ContextPanel";
import StubSurface from "../surfaces/StubSurface";
import SettingsSurface from "../surfaces/SettingsSurface";
import ChatSurface from "../surfaces/ChatSurface";
import { useApplyTheme } from "../theme/useApplyTheme";

export default function Shell() {
  useApplyTheme();
  return (
    <div className="h-full flex flex-col bg-bg text-text">
      <Header />
      <div className="flex-1 flex min-h-0 relative">
        <LeftRail />
        <main className="flex-1 min-w-0 overflow-y-auto">
          <Routes>
            <Route path="/" element={<ChatSurface />} />
            <Route path="/files" element={<StubSurface name="Files" />} />
            <Route path="/tools" element={<StubSurface name="Tools" />} />
            <Route path="/memory" element={<StubSurface name="Memory" />} />
            <Route path="/inspect" element={<StubSurface name="Inspect" />} />
            <Route path="/models" element={<StubSurface name="Models" />} />
            <Route path="/doctor" element={<StubSurface name="Doctor" />} />
            <Route path="/settings" element={<SettingsSurface />} />
          </Routes>
        </main>
        <ContextPanel />
      </div>
    </div>
  );
}
