import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

interface Source {
  id: string;
  name: string;
  kind: string;
  chunks: number;
  created_at?: string;
}

interface SearchHit {
  anchor?: { source_id: string; file: string; kind: string; page?: number | null; chunk?: number; hash: string };
  snippet?: string;
}

const inputCls =
  "w-full rounded-xl border border-edge bg-canvas px-3 py-2 text-[13.5px] outline-none transition-colors placeholder:text-ink-3 focus:border-accent/60";

/** 项目资料库：上传、检索与清理。所有资料都将作为可追溯证据供研究流程检索。 */
export function SourcesView() {
  const input = useRef<HTMLInputElement>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("hybrid");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  const load = useCallback(() => {
    api.get<Source[]>("/api/sources").then(setSources).catch((e: Error) => setNotice(e.message));
  }, []);

  useEffect(() => {
    document.title = "研究助手 · 资料库";
    load();
  }, [load]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setNotice("");
    try {
      const body = new FormData();
      Array.from(files).forEach((file) => body.append("files", file));
      const response = await fetch("/api/sources/upload", { method: "POST", body });
      const result = (await response.json()) as { detail?: string; sources?: Source[] };
      if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
      setNotice(`已导入 ${result.sources?.length ?? files.length} 份资料，可立即被研究任务检索。`);
      load();
    } catch (e) {
      setNotice(`导入失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function search() {
    const q = query.trim();
    if (!q) {
      setHits([]);
      return;
    }
    setBusy(true);
    setNotice("");
    try {
      setHits(await api.get<SearchHit[]>(`/api/sources/search?q=${encodeURIComponent(q)}&mode=${mode}`));
    } catch (e) {
      setNotice(`检索失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function remove(source: Source) {
    if (!window.confirm(`从资料库移除「${source.name}」？不会删除原始文件。`)) return;
    try {
      await api.del(`/api/sources/${encodeURIComponent(source.id)}`);
      setHits((items) => items.filter((item) => item.anchor?.source_id !== source.id));
      load();
    } catch (e) {
      setNotice(`移除失败：${(e as Error).message}`);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-7 py-8">
      <header className="mb-6">
        <h1 className="text-[22px] font-semibold tracking-tight">资料库</h1>
        <p className="mt-1 text-[13.5px] text-ink-2">上传项目资料，研究代理会按页码和片段检索，并保留可追溯锚点。</p>
      </header>

      <section className="rounded-2xl border border-edge bg-surface p-5 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-[14px] font-semibold">导入资料</h2>
            <p className="mt-1 text-[12.5px] text-ink-3">支持 PDF、DOCX、Markdown、TXT 和 BibTeX；单个文件最大 50 MB。</p>
          </div>
          <input ref={input} type="file" multiple accept=".pdf,.docx,.md,.txt,.bib" className="hidden" onChange={(event) => void upload(event.target.files)} />
          <button type="button" onClick={() => input.current?.click()} disabled={busy} className="rounded-xl bg-accent px-4 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50">
            {busy ? "处理中…" : "选择文件"}
          </button>
        </div>
        {notice && <p className="mt-3 text-[12.5px] text-ink-2">{notice}</p>}
      </section>

      <section className="mt-5 rounded-2xl border border-edge bg-surface p-5 shadow-card">
        <h2 className="text-[14px] font-semibold">证据检索</h2>
        <form className="mt-3 flex gap-2" onSubmit={(event) => { event.preventDefault(); void search(); }}>
          <input className={inputCls} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入研究问题、方法或关键词" />
          <select value={mode} onChange={(event) => setMode(event.target.value)} aria-label="检索模式" className="shrink-0 rounded-xl border border-edge bg-canvas px-2.5 text-[12px] outline-none focus:border-accent/60">
            <option value="hybrid">混合检索</option>
            <option value="keyword">关键词</option>
            <option value="semantic">语义近邻</option>
          </select>
          <button type="submit" disabled={busy} className="shrink-0 rounded-xl border border-edge px-4 text-[13px] font-medium hover:bg-surface-2 disabled:opacity-50">检索</button>
        </form>
        {hits.length > 0 && <div className="mt-4 space-y-3">
          {hits.map((hit, index) => <article key={`${hit.anchor?.source_id}-${hit.anchor?.chunk ?? index}`} className="rounded-xl border border-edge/70 bg-canvas p-3.5">
            <div className="mb-1.5 text-[11.5px] font-medium text-accent">{hit.anchor?.file}{hit.anchor?.page ? ` · 第 ${hit.anchor.page} 页` : ""}{hit.anchor?.chunk != null ? ` · 片段 ${hit.anchor.chunk + 1}` : ""}</div>
            <p className="whitespace-pre-wrap text-[12.5px] leading-5 text-ink-2">{hit.snippet}</p>
          </article>)}
        </div>}
        {query && !busy && hits.length === 0 && <p className="mt-4 text-[12.5px] text-ink-3">没有找到匹配片段。</p>}
      </section>

      <section className="mt-5 overflow-hidden rounded-2xl border border-edge bg-surface shadow-card">
        <div className="flex items-center justify-between border-b border-edge px-5 py-3"><h2 className="text-[14px] font-semibold">已导入资料</h2><span className="text-[12px] text-ink-3">{sources.length} 份</span></div>
        {sources.length === 0 ? <p className="p-5 text-[13px] text-ink-3">尚未导入资料。</p> : <ul>{sources.map((source) => <li key={source.id} className="flex items-center gap-3 border-b border-edge/60 px-5 py-3 last:border-0"><span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-tint text-sm">{source.kind === "pdf" ? "PDF" : "文"}</span><div className="min-w-0 flex-1"><div className="truncate text-[13px] font-medium">{source.name}</div><div className="mt-0.5 text-[11.5px] text-ink-3">{source.kind.toUpperCase()} · {source.chunks} 个检索片段</div></div><button type="button" onClick={() => void remove(source)} className="rounded-lg px-2 py-1 text-[12px] text-ink-3 hover:text-danger">移除</button></li>)}</ul>}
      </section>
    </div>
  );
}
