import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import TopologyGraph from "./pages/TopologyGraph.jsx";
import FraudRings from "./pages/FraudRings.jsx";
import EntityInspector from "./pages/EntityInspector.jsx";
import CaseFiles from "./pages/CaseFiles.jsx";
import GNNModels from "./pages/GNNModels.jsx";
import PipelineLogs from "./pages/PipelineLogs.jsx";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<TopologyGraph />} />
        <Route path="/rings" element={<FraudRings />} />
        <Route path="/entities" element={<EntityInspector />} />
        <Route path="/cases" element={<CaseFiles />} />
        <Route path="/models" element={<GNNModels />} />
        <Route path="/logs" element={<PipelineLogs />} />
      </Route>
    </Routes>
  );
}
