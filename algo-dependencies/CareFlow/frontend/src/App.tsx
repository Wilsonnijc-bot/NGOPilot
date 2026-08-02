import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import VolunteerUpload from "./pages/VolunteerUpload";
import VolunteerReview from "./pages/VolunteerReview";
import History from "./pages/History";
import HistoryDetail from "./pages/HistoryDetail";
import HomeVisit from "./pages/HomeVisit";
import HomeVisitReview from "./pages/HomeVisitReview";
import WelfareForm from "./pages/WelfareForm";
import ThetaUpload from "./pages/ThetaUpload";
import ThetaAudit from "./pages/ThetaAudit";
import Templates from "./pages/Templates";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/volunteer/upload" element={<VolunteerUpload />} />
        <Route path="/volunteer/review/:batchId" element={<VolunteerReview />} />
        <Route path="/history" element={<History />} />
        <Route path="/history/:batchId" element={<HistoryDetail />} />
        <Route path="/templates" element={<Templates />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/home-visit" element={<HomeVisit />} />
        <Route path="/home-visit/sessions/:sessionId" element={<HomeVisitReview />} />
        <Route path="/welfare-form" element={<WelfareForm />} />
        <Route path="/theta/upload" element={<ThetaUpload />} />
        <Route path="/theta/audit/:templateId" element={<ThetaAudit />} />
      </Route>
    </Routes>
  );
}
