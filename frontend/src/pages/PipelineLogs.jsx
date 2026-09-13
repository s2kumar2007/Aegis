import { useState } from "react";
import api from "../api";
import { Panel } from "../components/Card.jsx";

export default function PipelineLogs() {
  const [log, setLog] = useState([]);
  const [busy, setBusy] = useState(false);

  function append(line, tone = "slate-300") {
    setLog((l) => [...l, { t: new Date().toISOString(), line, tone }]);
  }

  async function runPipeline() {
    setBusy(true);
    append("Triggering detection pipeline…");
    try {
      const res = await api.runPipeline();
      append(`Pipeline complete — scored_accounts=${res.scored_accounts ?? "n/a"}`, "ok");
    } catch (e) {
      append(`Pipeline failed: ${e.message}`, "danger");
    } finally {
      setBusy(false);
    }
  }

  async function runAdaptation() {
    setBusy(true);
    append("Triggering adaptation cycle…");
    try {
      const res = await api.runAdaptation();
      append(`Adaptation complete — ${res.events?.length ?? 0} event(s)`, "ok");
      (res.events || []).forEach((ev) =>
        append(`  ring=${ev.ring_id} threshold ${ev.old_threshold?.toFixed(2)} -> ${ev.new_threshold?.toFixed(2)}`)
      );
    } catch (e) {
      append(`Adaptation failed: ${e.message}`, "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-3 space-y-3 max-w-3xl">
      <div className="flex gap-2">
        <button
          disabled={busy}
          onClick={runPipeline}
          className="px-3 py-1.5 bg-amber text-ink text-sm font-medium rounded disabled:opacity-50"
        >
          Run Detection Pipeline
        </button>
        <button
          disabled={busy}
          onClick={runAdaptation}
          className="px-3 py-1.5 border border-line text-sm rounded disabled:opacity-50"
        >
          Trigger Adaptation
        </button>
      </div>

      <Panel title="Session Log">
        <div className="mono text-xs space-y-1 max-h-[60vh] overflow-auto">
          {log.length === 0 && <div className="text-muted">No actions run yet this session.</div>}
          {log.map((entry, i) => (
            <div key={i} className={`text-${entry.tone}`}>
              <span className="text-muted">{entry.t.slice(11, 19)}</span> {entry.line}
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
