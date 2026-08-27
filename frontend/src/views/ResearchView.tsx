import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

type Overview = { counts: Record<string, number>; uncovered_claims: number };
type Item = { id: string; kind: string; title: string; body: string; status: string; version: number };
type Claim = { id: string; text: string; status: string; confidence: number | null; evidence_links: { evidence_id: string; relation: string }[] };
type Decision = { id: string; title: string; rationale: string; status: string };
type Matrix = { rows: { claim: { id: string; text: string; status: string; confidence: number | null }; cells: { evidence_id: string; relation: string; evidence: { source_anchor: string; excerpt: string; artifact_path?: string | null } }[] }[]; unlinked_evidence: { id: string; source_anchor: string; excerpt: string }[]; summary: { claims: { total: number; supported: number; uncovered: number; conflicted?: number }; stale_evidence?: number; ready_for_synthesis: boolean } };

const KIND_LABEL: Record<string, string> = { question: "研究问题", hypothesis: "假设", objective: "目标", note: "笔记" };

export function ResearchView() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [matrix, setMatrix] = useState<Matrix | null>(null);
  const [tab, setTab] = useState<"overview" | "matrix">("overview");
  const [title, setTitle] = useState("");
  const [claimText, setClaimText] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [o, i, c, d, m] = await Promise.all([
      api.get<Overview>("/api/research/overview"),
      api.get<Item[]>("/api/research/items"),
      api.get<Claim[]>("/api/research/claims"),
      api.get<Decision[]>("/api/research/decisions"),
      api.get<Matrix>("/api/research/evidence-matrix"),
    ]);
    setOverview(o); setItems(i); setClaims(c); setDecisions(d); setMatrix(m);
  }, []);

  useEffect(() => { refresh().catch(() => {}); }, [refresh]);

  async function addItem(kind: "question" | "hypothesis") {
    if (!title.trim()) return;
    setBusy(true);
    try { await api.post("/api/research/items", { kind, title }); setTitle(""); await refresh(); } finally { setBusy(false); }
  }
  async function addClaim() {
    if (!claimText.trim()) return;
    setBusy(true);
    try { await api.post("/api/research/claims", { text: claimText }); setClaimText(""); await refresh(); } finally { setBusy(false); }
  }

  return <div className="mx-auto max-w-6xl p-6">
    <div className="mb-6 flex items-start justify-between gap-4">
      <div><h1 className="text-xl font-semibold">研究工作台</h1><p className="mt-1 text-sm text-ink-2">把问题、证据、结论和决策串成可追溯的研究图谱。</p></div>
      <button type="button" onClick={() => refresh().catch(() => {})} className="rounded-lg border border-edge px-3 py-1.5 text-xs hover:border-accent/50">刷新</button>
    </div>
    <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-6">
      {[["问题/假设", (overview?.counts.research_items ?? 0)], ["主张", overview?.counts.claims ?? 0], ["证据", overview?.counts.evidence ?? 0], ["决策", overview?.counts.decisions ?? 0], ["运行", overview?.counts.research_runs ?? 0], ["待补证据", overview?.uncovered_claims ?? 0]].map(([label, value]) => <div key={String(label)} className={`rounded-xl border p-3 ${label === "待补证据" && Number(value) > 0 ? "border-warn/40 bg-warn/5" : "border-edge bg-surface"}`}><div className="text-[11px] text-ink-3">{label}</div><div className="mt-1 text-2xl font-semibold">{value}</div></div>)}
    </div>
    <div className="mb-6 grid gap-4 lg:grid-cols-2">
      <section className="rounded-xl border border-edge bg-surface p-4"><h2 className="mb-3 text-sm font-semibold">新增研究问题 / 假设</h2><div className="flex gap-2"><input value={title} onChange={e => setTitle(e.target.value)} placeholder="例如：数据稀疏时方法是否仍稳健？" className="min-w-0 flex-1 rounded-lg border border-edge bg-canvas px-3 py-2 text-sm outline-none focus:border-accent" /><button disabled={busy} onClick={() => addItem("question")} className="rounded-lg bg-accent px-3 py-2 text-xs text-white disabled:opacity-50">问题</button><button disabled={busy} onClick={() => addItem("hypothesis")} className="rounded-lg border border-edge px-3 py-2 text-xs disabled:opacity-50">假设</button></div></section>
      <section className="rounded-xl border border-edge bg-surface p-4"><h2 className="mb-3 text-sm font-semibold">记录一个可审计主张</h2><div className="flex gap-2"><input value={claimText} onChange={e => setClaimText(e.target.value)} placeholder="例如：方法 A 在三个数据集上优于基线" className="min-w-0 flex-1 rounded-lg border border-edge bg-canvas px-3 py-2 text-sm outline-none focus:border-accent" /><button disabled={busy} onClick={addClaim} className="rounded-lg bg-accent px-3 py-2 text-xs text-white disabled:opacity-50">记录</button></div></section>
    </div>
    <div className="mb-4 flex gap-1 rounded-xl bg-surface-2 p-1"><button onClick={() => setTab("overview")} className={`flex-1 rounded-lg px-3 py-1.5 text-xs font-medium ${tab === "overview" ? "bg-surface shadow-sm" : "text-ink-2"}`}>对象总览</button><button onClick={() => setTab("matrix")} className={`flex-1 rounded-lg px-3 py-1.5 text-xs font-medium ${tab === "matrix" ? "bg-surface shadow-sm" : "text-ink-2"}`}>证据矩阵</button></div>
    {tab === "matrix" ? <section className="rounded-xl border border-edge bg-surface p-4"><div className="mb-3 flex items-center justify-between"><div><h2 className="text-sm font-semibold">主张—证据矩阵</h2><p className="mt-1 text-[11px] text-ink-3">每条主张都应能追溯到来源片段或分析产物。</p></div><div className="text-right text-xs text-ink-3"><div>{matrix?.summary.claims.supported ?? 0}/{matrix?.summary.claims.total ?? 0} 已覆盖</div><div className="mt-0.5 text-[10px]">冲突 {matrix?.summary.claims.conflicted ?? 0} · 过期证据 {matrix?.summary.stale_evidence ?? 0}</div></div></div>{matrix?.rows.length ? <div className="space-y-3">{matrix.rows.map(row => <div key={row.claim.id} className="rounded-xl border border-edge/70 p-3"><div className="flex gap-2"><span className="flex-1 text-xs font-medium">{row.claim.text}</span><span className={`text-[10px] ${row.cells.length ? "text-ok" : "text-warn"}`}>{row.cells.length ? `${row.cells.length} 条证据` : "待补证据"}</span></div>{row.cells.length > 0 && <div className="mt-2 space-y-1.5">{row.cells.map(cell => <div key={`${row.claim.id}-${cell.evidence_id}`} className="rounded-lg bg-surface-2 p-2 text-[10.5px] text-ink-2"><span className="font-medium text-accent">{cell.relation}</span> · {cell.evidence.source_anchor || cell.evidence.artifact_path || "未命名来源"}<div className="mt-0.5 line-clamp-2 text-ink-3">{cell.evidence.excerpt}</div></div>)}</div>}</div>)}</div> : <p className="py-8 text-center text-xs text-ink-3">尚无主张或证据链接。</p>}</section> : <div className="grid gap-4 lg:grid-cols-3">
      <section className="rounded-xl border border-edge bg-surface p-4"><h2 className="mb-3 text-sm font-semibold">研究问题与假设</h2>{items.length === 0 ? <p className="text-xs text-ink-3">尚未记录。</p> : <div className="space-y-2">{items.slice(0, 12).map(item => <div key={item.id} className="rounded-lg border border-edge/70 p-2.5"><div className="flex justify-between gap-2"><span className="text-xs font-medium">{item.title}</span><span className="text-[10px] text-accent">{KIND_LABEL[item.kind] || item.kind}</span></div><div className="mt-1 text-[10px] text-ink-3">v{item.version} · {item.status}</div></div>)}</div>}</section>
      <section className="rounded-xl border border-edge bg-surface p-4"><h2 className="mb-3 text-sm font-semibold">证据覆盖</h2>{claims.length === 0 ? <p className="text-xs text-ink-3">尚未记录主张。</p> : <div className="space-y-2">{claims.slice(0, 12).map(claim => <div key={claim.id} className="rounded-lg border border-edge/70 p-2.5"><div className="text-xs">{claim.text}</div><div className={`mt-1 text-[10px] ${claim.evidence_links.length ? "text-ok" : "text-warn"}`}>{claim.evidence_links.length ? `${claim.evidence_links.length} 条证据已关联` : "待补证据"}</div></div>)}</div>}</section>
      <section className="rounded-xl border border-edge bg-surface p-4"><h2 className="mb-3 text-sm font-semibold">决策日志</h2>{decisions.length === 0 ? <p className="text-xs text-ink-3">工作流完成后可在此沉淀决策。</p> : <div className="space-y-2">{decisions.slice(0, 12).map(decision => <div key={decision.id} className="rounded-lg border border-edge/70 p-2.5"><div className="text-xs font-medium">{decision.title}</div><div className="mt-1 line-clamp-2 text-[10px] text-ink-3">{decision.rationale || "无理由"}</div></div>)}</div>}</section>
    </div>}
  </div>;
}
