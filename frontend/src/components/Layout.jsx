import { NavLink, Outlet } from "react-router-dom";
import { useEffect, useState } from "react";
import api from "../api";

const NAV = [
  { to: "/", label: "Topology Graph", group: "INVESTIGATIONS" },
  { to: "/rings", label: "Fraud Rings", group: "INVESTIGATIONS" },
  { to: "/entities", label: "Entity Inspector", group: "INVESTIGATIONS" },
  { to: "/cases", label: "Case Files", group: "INVESTIGATIONS" },
  { to: "/models", label: "GNN Models", group: "TELEMETRY & ML" },
  { to: "/logs", label: "Pipeline Logs", group: "TELEMETRY & ML" },
];

export default function Layout() {
  const [health, setHealth] = useState({ accounts: 0, rings: 0 });

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const [accounts, rings] = await Promise.all([api.accounts(), api.rings()]);
        if (alive) setHealth({ accounts: accounts.length, rings: rings.length });
      } catch (e) {
        // header stays at last-known values on transient errors
      }
    }
    load();
    const id = setInterval(load, 15000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  return (
    <div className="min-h-screen bg-ink text-slate-200 flex">
      <aside className="w-56 border-r border-line flex flex-col">
        <div className="px-4 py-4 border-b border-line">
          <div className="text-amber font-semibold tracking-tight text-sm mono">AEGIS FINT</div>
          <div className="text-[11px] text-muted mono">v1.0 · LOCAL</div>
        </div>
        <nav className="flex-1 px-2 py-3 space-y-4">
          {["INVESTIGATIONS", "TELEMETRY & ML"].map((group) => (
            <div key={group}>
              <div className="px-2 text-[10px] tracking-wider text-muted mono mb-1">{group}</div>
              {NAV.filter((n) => n.group === group).map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.to === "/"}
                  className={({ isActive }) =>
                    `block px-2 py-1.5 rounded text-sm mb-0.5 ${
                      isActive ? "bg-panel text-amber" : "text-slate-300 hover:bg-panel"
                    }`
                  }
                >
                  {n.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-12 border-b border-line flex items-center justify-between px-4 mono text-xs">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-ok inline-block" />
            <span className="text-slate-200">AEGIS FRAUD INTELLIGENCE</span>
            <span className="text-muted">·</span>
            <span className="text-muted">Monitored: {health.accounts.toLocaleString()} accts</span>
            <span className="text-muted">·</span>
            <span className="text-danger">Critical: {health.rings} Active</span>
          </div>
        </header>
        <main className="flex-1 min-w-0 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
