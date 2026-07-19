import { Route, Routes } from "react-router-dom";
import Header from "./Header";
import LeftRail from "./LeftRail";
import ContextPanel from "./ContextPanel";
import SettingsSurface from "../surfaces/SettingsSurface";
import ChatSurface from "../surfaces/ChatSurface";
import InspectSurface from "../surfaces/InspectSurface";
import DoctorSurface from "../surfaces/DoctorSurface";
import ModelsSurface from "../surfaces/ModelsSurface";
import ToolsSurface from "../surfaces/ToolsSurface";
import FilesSurface from "../surfaces/FilesSurface";
import MemorySurface from "../surfaces/MemorySurface";
import { useApplyTheme } from "../theme/useApplyTheme";
import { useEnsureSession } from "../session/useEnsureSession";

export default function Shell() {
  useApplyTheme();
  useEnsureSession();
  return (
    <div className="h-full flex flex-col bg-bg text-text">
      <Header />
      <div className="flex-1 flex min-h-0 relative">
        <LeftRail />
        <main className="flex-1 min-w-0 overflow-y-auto">
          <Routes>
            <Route path="/" element={<ChatSurface />} />
            <Route path="/files" element={<FilesSurface />} />
            <Route path="/tools" element={<ToolsSurface />} />
            <Route path="/memory" element={<MemorySurface />} />
            <Route path="/inspect" element={<InspectSurface />} />
            <Route path="/models" element={<ModelsSurface />} />
            <Route path="/doctor" element={<DoctorSurface />} />
            <Route path="/settings" element={<SettingsSurface />} />
          </Routes>
        </main>
        <ContextPanel />
      </div>
    </div>
  );
}
