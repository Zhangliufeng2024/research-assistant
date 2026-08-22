/* 文库视图：左（搜索/排序列表）· 右（概览/图表画廊/进度日志 Tab） */
import { S } from "../store.js";
import { api } from "../api.js";
import { el, basename, fmtNum, fmtDate } from "../format.js";
import { toast } from "../components/toast.js";
import { showImage, showPdf, confirmDialog } from "../components/modal.js";
import { renderMarkdown } from "../md.js";
import { T } from "../i18n.js";

let cleanup = null;

export function renderPapersView(root, onCleanup) {
  if (cleanup) cleanup();
  let ui = {};
  let currentName = null;
  let activeTab = "overview";

  const view = el("section", { class: "view view-papers" });

  /* ---- 左栏 ---- */
  const searchInput = el("input", { class: "input", placeholder: "搜索标题 / 主题…" });
  searchInput.addEventListener("input", renderList);
  const sortSel = el("select", { class: "select" },
    el("option", { value: "date" }, "最新优先"),
    el("option", { value: "words" }, "字数优先"));
  sortSel.addEventListener("change", renderList);
  ui.list = el("div", { class: "plist" }, el("div", { class: "empty" }, "加载中…"));
  ui.count = el("span", { class: "count" }, "");

  /* ---- 右栏 ---- */
  ui.detail = el("div", { class: "panel paper-detail" },
    el("div", { class: "empty", style: "margin:auto" },
      el("span", { class: "empty-icon" }, "▤"), "选择左侧文档查看详情"));

  view.append(
    el("div", { class: "panel papers-side" },
      el("div", { class: "papers-tools" },
        searchInput,
        el("div", { class: "papers-tools-row" }, sortSel)),
      el("div", { class: "panel-head" }, "文档库", ui.count),
      ui.list),
    ui.detail);
  root.append(view);

  /* ================= 数据 ================= */
  async function loadPapers() {
    try {
      const papers = await api.get("/api/papers");
      S.set({ papers });
      renderList();
      if (currentName && papers.some((p) => p.name === currentName)) openDetail(currentName);
      else if (papers.length) openDetail(papers[0].name);
    } catch (e) {
      ui.list.innerHTML = "";
      ui.list.append(el("div", { class: "empty" }, `加载失败：${e.message}`));
    }
  }

  function filtered() {
    const kw = searchInput.value.trim().toLowerCase();
    let arr = S.get("papers").filter((p) =>
      !kw || (p.title || "").toLowerCase().includes(kw) || (p.topic || "").toLowerCase().includes(kw));
    if (sortSel.value === "words") arr = [...arr].sort((a, b) => (b.word_count || 0) - (a.word_count || 0));
    return arr;
  }

  function renderList() {
    const arr = filtered();
    ui.count.textContent = `(${arr.length})`;
    ui.list.innerHTML = "";
    if (!arr.length) {
      ui.list.append(el("div", { class: "empty" },
        el("span", { class: "empty-icon" }, "▢"), "没有匹配的文档"));
      return;
    }
    for (const p of arr) {
      const card = el("div", { class: `pcard ${p.name === currentName ? "active" : ""}` });
      card.append(
        el("div", { class: "pcard-title", title: p.title || p.topic }, p.title || p.topic || p.name),
        el("div", { class: "pcard-meta" },
          el("span", { class: `dot ${p.status === "success" ? "ok" : p.status === "partial" ? "warn" : "err"}` }),
          el("span", {}, T.status[p.status] || p.status),
          el("span", {}, fmtDate(p.date)),
          p.word_count ? el("span", {}, `${fmtNum(p.word_count)}字`) : null));
      card.addEventListener("click", () => openDetail(p.name));
      ui.list.append(card);
    }
  }

  async function openDetail(name) {
    currentName = name;
    renderList();
    ui.detail.innerHTML = "";
    ui.detail.append(el("div", { class: "empty", style: "margin:auto" },
      el("span", { class: "spin" }), el("span", { style: "margin-left:8px" }, "加载中…")));
    try {
      const paper = await api.get(`/api/papers/${encodeURIComponent(name)}`);
      renderDetail(paper);
    } catch (e) {
      ui.detail.innerHTML = "";
      ui.detail.append(el("div", { class: "empty", style: "margin:auto" }, `加载失败：${e.message}`));
    }
  }

  /* ================= 详情渲染 ================= */
  function renderDetail(p) {
    ui.detail.innerHTML = "";
    const files = p.files || {};

    const head = el("div", { class: "pd-head" },
      el("div", { class: "pd-title", textContent: p.title || p.topic || p.name }),
      el("div", { class: "pd-meta" },
        el("span", { class: `badge ${p.status === "success" ? "b-ok" : p.status === "partial" ? "b-warn" : "b-err"}` }, T.status[p.status] || p.status),
        el("span", {}, fmtDate(p.date)),
        p.word_count ? el("span", {}, `${fmtNum(p.word_count)} 字`) : null,
        p.figures_count ? el("span", {}, `图 ${p.figures_count}`) : null,
        p.citations_count ? el("span", {}, `引文 ${p.citations_count}`) : null),
      el("div", { class: "pd-actions" },
        el("a", { class: "btn btn-amber btn-sm", href: `/api/papers/${encodeURIComponent(p.name)}/export`, download: "" }, "⤓ 打包下载 ZIP"),
        files.docx_final ? el("a", { class: "btn btn-ghost btn-sm", href: fileUrl(p.name, files.docx_final), download: "" }, "Word") : null,
        files.pdf_final ? el("button", { class: "btn btn-ghost btn-sm", onclick: () => showPdf(fileUrl(p.name, files.pdf_final), basename(files.pdf_final)) }, "PDF 预览") : null,
        el("span", { style: "flex:1" }),
        el("button", { class: "btn btn-danger btn-sm", onclick: () => deletePaper(p) }, "删除")));

    const body = el("div", { class: "pd-body" });
    const tabs = el("div", { class: "pd-tabs" });
    const tabDefs = [
      ["overview", "概览"],
      ["gallery", `图表${p.figures_count ? ` (${p.figures_count})` : ""}`],
      ["progress", "进度日志"],
    ];
    for (const [key, label] of tabDefs) {
      const b = el("button", { class: `pd-tab ${activeTab === key ? "active" : ""}`, onclick: () => { activeTab = key; renderDetail(p); } }, label);
      tabs.append(b);
    }

    if (activeTab === "gallery") renderGallery(body, p.name, files.figures || []);
    else if (activeTab === "progress") renderProgress(body, p);
    else renderOverview(body, p, files);

    ui.detail.append(head, tabs, body);
  }

  function fileUrl(name, path) {
    return `/api/papers/${encodeURIComponent(name)}/files/${encodeURIComponent(path)}`;
  }

  function renderOverview(body, p, files) {
    const group = (title, rows) => {
      if (!rows.length) return;
      const g = el("div", { class: "file-group" },
        el("div", { class: "file-group-title" }, title));
      for (const r of rows) {
        const row = el("div", { class: "file-row" },
          el("span", { class: "fname", title: r.path }, basename(r.path)));
        if (/\.pdf$/i.test(r.path)) {
          row.append(el("button", { class: "fact", onclick: () => showPdf(fileUrl(p.name, r.path), basename(r.path)) }, "预览"));
        }
        if (/\.(png|jpe?g|gif|svg)$/i.test(r.path)) {
          row.append(el("button", { class: "fact", onclick: () => showImage(fileUrl(p.name, r.path), basename(r.path)) }, "预览"));
        }
        row.append(el("a", { class: "fact", href: fileUrl(p.name, r.path), download: "" }, "下载"));
        g.append(row);
      }
      body.append(g);
    };

    group("最终版本", [files.docx_final, files.pdf_final, files.tex_final].filter(Boolean).map((f) => ({ path: f })));
    group("草稿", [...(files.docx_drafts || []), ...(files.pdf_drafts || []), ...(files.tex_drafts || [])].map((f) => ({ path: f })));
    group("参考文献", files.bibliography ? [{ path: files.bibliography }] : []);
    group("数据", (files.data || []).map((f) => ({ path: f })));
    group("来源", (files.sources || []).map((f) => ({ path: f })));

    if (p.summary_content) {
      body.append(el("div", { class: "file-group" },
        el("div", { class: "file-group-title" }, "摘要 SUMMARY.md"),
        el("div", { class: "md-content", html: renderMarkdown(p.summary_content) })));
    }
    if (!body.children.length) {
      body.append(el("div", { class: "empty" }, "该目录暂无文件"));
    }
  }

  function renderGallery(body, name, figures) {
    if (!figures.length) { body.append(el("div", { class: "empty" }, "没有图表")); return; }
    const grid = el("div", { class: "gallery" });
    for (const f of figures) {
      const item = el("div", { class: "g-item" },
        el("img", { src: fileUrl(name, f), alt: basename(f), loading: "lazy" }),
        el("div", { class: "g-name", title: basename(f) }, basename(f)));
      item.addEventListener("click", () => showImage(fileUrl(name, f), basename(f)));
      grid.append(item);
    }
    body.append(grid);
  }

  function renderProgress(body, p) {
    if (!p.progress_content) { body.append(el("div", { class: "empty" }, "无进度日志")); return; }
    body.append(el("div", { class: "md-content", html: renderMarkdown(p.progress_content) }));
  }

  async function deletePaper(p) {
    const ok = await confirmDialog(`确定删除「${p.title || p.name}」？\n整个目录（含全部产物）将被永久删除，不可恢复。`,
      { okText: "删除" });
    if (!ok) return;
    try {
      await api.del(`/api/papers/${encodeURIComponent(p.name)}`);
      toast("已删除", "ok");
      currentName = null;
      loadPapers();
    } catch (e) {
      toast(`删除失败：${e.message}`, "err");
    }
  }

  const unsub = S.subscribe((state) => {
    if (state.papers && ui.list) renderList();
  });

  loadPapers();
  cleanup = () => { unsub(); };
  onCleanup(() => { if (cleanup) { cleanup(); cleanup = null; } });
}
