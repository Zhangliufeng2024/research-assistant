/* Research Assistant — Frontend Logic */

(function () {
  "use strict";

  // === Stage mapping ===
  const STAGE_NAMES = {
    initialization: "初始化",
    planning: "规划中",
    research: "研究中",
    revision: "质量修订中",
    finalization: "定稿中",
    writing: "写作中",
    compilation: "编译中",
    complete: "已完成",
    cancelled: "已停止",
    error: "出错",
  };

  const STAGE_PROGRESS = {
    initialization: 10,
    planning: 25,
    research: 50,
    writing: 75,
    compilation: 90,
    complete: 100,
  };

  // === DOM refs ===
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const views = { task: $("#view-task"), papers: $("#view-papers") };
  const tabs = $$(".tab");

  const queryInput = $("#query");
  const multiAgentCheckbox = $("#multi-agent");
  const maxCostInput = $("#max-cost");
  const btnGenerate = $("#btn-generate");
  const btnStop = $("#btn-stop");
  const progressPanel = $("#progress-panel");
  const progressBar = $("#progress-bar");
  const progressStage = $("#progress-stage");
  const progressLog = $("#progress-log");
  const resultCard = $("#result-card");
  const resultMeta = $("#result-meta");
  const resultActions = $("#result-actions");
  const errorCard = $("#error-card");
  const errorMessage = $("#error-message");

  const papersItems = $("#papers-items");
  const papersCount = $("#papers-count");
  const papersDetail = $("#papers-detail");

  let ws = null;
  let currentPaperName = null;
  let currentTaskId = null;

  // === View switching ===
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const view = tab.dataset.view;
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      Object.values(views).forEach((v) => v.classList.remove("active"));
      views[view].classList.add("active");

      if (view === "papers") loadPapers();
    });
  });

  // === Task generation ===
  btnGenerate.addEventListener("click", startGeneration);

  queryInput.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key === "Enter") startGeneration();
  });

  function startGeneration() {
    const query = queryInput.value.trim();
    if (!query) {
      queryInput.focus();
      return;
    }

    resetUI();
    progressPanel.classList.remove("hidden");
    btnGenerate.disabled = true;
    btnGenerate.textContent = "生成中...";

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${location.host}/ws/generate`);

    ws.onopen = () => {
      const payload = {
        action: "start",
        query: query,
        multi_agent: multiAgentCheckbox.checked,
        track_token_usage: true,
      };
      const maxCost = parseFloat(maxCostInput.value);
      if (!Number.isNaN(maxCost) && maxCost > 0) {
        payload.max_cost_usd = maxCost;
      }
      ws.send(JSON.stringify(payload));
      btnStop.classList.remove("hidden");
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      handleMessage(msg);
    };

    ws.onerror = () => {
      showError("WebSocket 连接失败，请检查服务是否运行");
    };

    ws.onclose = () => {
      btnGenerate.disabled = false;
      btnGenerate.textContent = "开始生成";
      btnStop.classList.add("hidden");
      currentTaskId = null;
      ws = null;
    };
  }

  function handleMessage(msg) {
    switch (msg.type) {
      case "connected":
        currentTaskId = msg.task_id || null;
        appendLog("已连接，任务启动中...");
        break;

      case "progress":
        if (msg.stage === "cancelled") {
          appendLog(msg.message || "任务已停止");
          btnStop.classList.add("hidden");
          btnGenerate.disabled = false;
          btnGenerate.textContent = "开始生成";
          break;
        }
        handleProgress(msg);
        break;

      case "text":
        // Full text output — not displayed in progress (it's internal LLM text)
        break;

      case "result":
        btnStop.classList.add("hidden");
        handleResult(msg);
        break;

      case "error":
        btnStop.classList.add("hidden");
        showError(msg.message);
        break;

      case "done":
        btnStop.classList.add("hidden");
        if (ws) ws.close();
        break;
    }
  }

  async function stopGeneration() {
    if (!currentTaskId) return;
    btnStop.disabled = true;
    btnStop.textContent = "停止中...";
    appendLog("正在请求停止任务...");
    try {
      await fetch(`/api/tasks/${encodeURIComponent(currentTaskId)}/stop`, {
        method: "POST",
      });
    } catch (e) {
      appendLog(`停止请求失败: ${e.message}`);
    } finally {
      btnStop.disabled = false;
      btnStop.textContent = "停止";
    }
  }

  btnStop.addEventListener("click", stopGeneration);

  function handleProgress(msg) {
    const stage = msg.stage || "initialization";
    const stageName = STAGE_NAMES[stage] || stage;
    const percent = STAGE_PROGRESS[stage] || 0;

    progressStage.textContent = stageName;
    progressBar.style.width = percent + "%";

    if (msg.message) {
      const time = msg.timestamp
        ? new Date(msg.timestamp).toLocaleTimeString("zh-CN", { hour12: false })
        : "";
      appendLog(msg.message, time);
    }
  }

  function handleResult(msg) {
    progressPanel.classList.add("hidden");

    if (msg.status === "failed") {
      const errors = msg.errors || [];
      showError(errors.join("\n") || "文档生成失败");
      return;
    }

    resultCard.classList.remove("hidden");

    const meta = msg.metadata || {};
    const parts = [];
    if (meta.title) parts.push(`标题: ${meta.title}`);
    if (meta.word_count) parts.push(`字数: ${meta.word_count.toLocaleString()}`);
    if (msg.figures_count) parts.push(`图表: ${msg.figures_count}`);
    if (msg.citations && msg.citations.count)
      parts.push(`引用: ${msg.citations.count}`);

    resultMeta.textContent = parts.join("  |  ");

    const paperName = msg.paper_name || "";
    const files = msg.files || {};
    let actionsHTML = "";

    if (paperName) {
      actionsHTML += `<button class="btn btn-secondary" onclick="app.viewPaper('${esc(paperName)}')">查看文档</button>`;
    }
    if (files.docx_final) {
      actionsHTML += `<a class="btn btn-secondary" href="/api/papers/${esc(paperName)}/files/${esc(files.docx_final)}" download>下载 Word</a>`;
    }
    if (files.pdf_final) {
      actionsHTML += `<a class="btn btn-secondary" href="/api/papers/${esc(paperName)}/files/${esc(files.pdf_final)}" download>下载 PDF</a>`;
    }

    resultActions.innerHTML = actionsHTML;
  }

  function showError(message) {
    progressPanel.classList.add("hidden");
    resultCard.classList.add("hidden");
    errorCard.classList.remove("hidden");
    errorMessage.textContent = message;
    btnGenerate.disabled = false;
    btnGenerate.textContent = "开始生成";
  }

  function resetUI() {
    progressPanel.classList.add("hidden");
    resultCard.classList.add("hidden");
    errorCard.classList.add("hidden");
    progressLog.innerHTML = "";
    progressBar.style.width = "0%";
    progressStage.textContent = "初始化";
  }

  function appendLog(message, time) {
    const entry = document.createElement("div");
    entry.className = "log-entry";
    if (time) {
      entry.innerHTML = `<span class="log-time">${esc(time)}</span>${esc(message)}`;
    } else {
      entry.textContent = message;
    }
    progressLog.appendChild(entry);
    progressLog.scrollTop = progressLog.scrollHeight;
  }

  // === Papers Browser ===
  async function loadPapers() {
    papersItems.innerHTML = '<div class="loading">加载中...</div>';

    try {
      const res = await fetch("/api/papers");
      if (!res.ok) throw new Error("加载失败");
      const papers = await res.json();

      papersCount.textContent = `(${papers.length})`;

      if (papers.length === 0) {
        papersItems.innerHTML = '<div class="loading">暂无文档</div>';
        return;
      }

      papersItems.innerHTML = papers.map((p) => paperCardHTML(p)).join("");

      papersItems.querySelectorAll(".paper-card").forEach((card) => {
        card.addEventListener("click", () => {
          papersItems
            .querySelectorAll(".paper-card")
            .forEach((c) => c.classList.remove("selected"));
          card.classList.add("selected");
          loadPaperDetail(card.dataset.name);
        });
      });

      // Auto-select first or previously selected
      if (currentPaperName) {
        const target = papersItems.querySelector(
          `[data-name="${currentPaperName}"]`
        );
        if (target) {
          target.classList.add("selected");
          loadPaperDetail(currentPaperName);
          return;
        }
      }
      const first = papersItems.querySelector(".paper-card");
      if (first) {
        first.classList.add("selected");
        loadPaperDetail(first.dataset.name);
      }
    } catch (e) {
      papersItems.innerHTML = `<div class="loading">加载失败: ${esc(e.message)}</div>`;
    }
  }

  function paperCardHTML(p) {
    const statusMap = { success: "成功", partial: "部分", empty: "空", failed: "失败" };
    const statusLabel = statusMap[p.status] || p.status;
    const wordInfo = p.word_count ? ` · ${p.word_count.toLocaleString()}字` : "";

    return `
      <div class="paper-card" data-name="${esc(p.name)}">
        <div class="paper-card-topic" title="${esc(p.title || p.topic)}">${esc(p.title || p.topic)}</div>
        <div class="paper-card-date">${esc(p.date)}</div>
        <div class="paper-card-status">
          <span class="status-dot ${p.status}"></span>${statusLabel}${wordInfo}
        </div>
      </div>`;
  }

  async function loadPaperDetail(name) {
    currentPaperName = name;
    papersDetail.innerHTML = '<div class="loading">加载中...</div>';

    try {
      const res = await fetch(`/api/papers/${encodeURIComponent(name)}`);
      if (!res.ok) throw new Error("加载失败");
      const paper = await res.json();
      renderPaperDetail(paper);
    } catch (e) {
      papersDetail.innerHTML = `<div class="loading">加载失败: ${esc(e.message)}</div>`;
    }
  }

  function renderPaperDetail(paper) {
    const files = paper.files || {};
    const statusMap = { success: "成功", partial: "部分完成", empty: "空" };
    let html = "";

    // Header
    html += `<div class="detail-title">${esc(paper.title || paper.topic)}</div>`;
    html += `<div class="detail-meta">`;
    html += `<span class="detail-meta-item">${esc(paper.date)}</span>`;
    html += `<span class="detail-meta-item"><span class="status-dot ${paper.status}"></span>${statusMap[paper.status] || paper.status}</span>`;
    if (paper.word_count)
      html += `<span class="detail-meta-item">${paper.word_count.toLocaleString()} 字</span>`;
    if (paper.figures_count)
      html += `<span class="detail-meta-item">${paper.figures_count} 图表</span>`;
    if (paper.citations_count)
      html += `<span class="detail-meta-item">${paper.citations_count} 引用</span>`;
    html += `</div>`;

    // Final versions
    const finals = [];
    if (files.docx_final) finals.push({ name: pathBasename(files.docx_final), path: files.docx_final, icon: "📄" });
    if (files.pdf_final) finals.push({ name: pathBasename(files.pdf_final), path: files.pdf_final, icon: "📄" });
    if (files.tex_final) finals.push({ name: pathBasename(files.tex_final), path: files.tex_final, icon: "📄" });

    if (finals.length) {
      html += fileSection("最终版本", finals, paper.name);
    }

    // Drafts
    const drafts = [];
    (files.docx_drafts || []).forEach((f) => drafts.push({ name: pathBasename(f), path: f, icon: "📄" }));
    (files.pdf_drafts || []).forEach((f) => drafts.push({ name: pathBasename(f), path: f, icon: "📄" }));
    (files.tex_drafts || []).forEach((f) => drafts.push({ name: pathBasename(f), path: f, icon: "📄" }));
    if (drafts.length) {
      html += fileSection("草稿", drafts, paper.name);
    }

    // Figures
    const figures = (files.figures || []).map((f) => ({
      name: pathBasename(f),
      path: f,
      icon: "🖼",
      isImage: true,
    }));
    if (figures.length) {
      html += fileSection(`图表 (${figures.length})`, figures, paper.name);
    }

    // Bibliography
    if (files.bibliography) {
      html += fileSection("参考文献", [{ name: pathBasename(files.bibliography), path: files.bibliography, icon: "📄" }], paper.name);
    }

    // Data
    const dataFiles = (files.data || []).map((f) => ({ name: pathBasename(f), path: f, icon: "📄" }));
    if (dataFiles.length) {
      html += fileSection(`数据 (${dataFiles.length})`, dataFiles, paper.name);
    }

    // Sources
    const sourceFiles = (files.sources || []).map((f) => ({ name: pathBasename(f), path: f, icon: "📄" }));
    if (sourceFiles.length) {
      html += fileSection(`来源 (${sourceFiles.length})`, sourceFiles, paper.name);
    }

    // Summary
    if (paper.summary_content) {
      html += `<div class="detail-section">
        <div class="detail-section-title">摘要</div>
        <div class="detail-summary">${esc(paper.summary_content)}</div>
      </div>`;
    }

    // Delete
    html += `<div class="detail-delete">
      <button class="btn-danger" onclick="app.deletePaper('${esc(paper.name)}')">删除此文档</button>
    </div>`;

    papersDetail.innerHTML = html;
  }

  function fileSection(title, files, paperName) {
    let html = `<div class="detail-section">
      <div class="detail-section-title">${esc(title)}</div>`;

    files.forEach((f) => {
      const url = `/api/papers/${encodeURIComponent(paperName)}/files/${encodeURIComponent(f.path)}`;
      const actionLabel = f.isImage ? "预览" : "下载";
      const actionAttr = f.isImage
        ? `href="javascript:void(0)" onclick="app.previewImage('${esc(url)}')"`
        : `href="${url}" download`;

      html += `<div class="file-item">
        <span class="file-name"><span class="file-icon">${f.icon}</span>${esc(f.name)}</span>
        <a class="file-action" ${actionAttr}>${actionLabel}</a>
      </div>`;
    });

    html += `</div>`;
    return html;
  }

  // === Image Preview ===
  function previewImage(url) {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `<img class="modal-image" src="${url}" alt="预览">`;
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) overlay.remove();
    });
    document.body.appendChild(overlay);

    document.addEventListener(
      "keydown",
      function handler(e) {
        if (e.key === "Escape") {
          overlay.remove();
          document.removeEventListener("keydown", handler);
        }
      }
    );
  }

  // === View Paper (from result card) ===
  function viewPaper(name) {
    currentPaperName = name;
    // Switch to papers tab
    tabs.forEach((t) => t.classList.remove("active"));
    $$('.tab[data-view="papers"]').forEach((t) => t.classList.add("active"));
    Object.values(views).forEach((v) => v.classList.remove("active"));
    views.papers.classList.add("active");
    loadPapers();
  }

  // === Delete Paper ===
  async function deletePaper(name) {
    if (!confirm(`确定要删除文档 "${name}" 吗？此操作不可撤销。`)) return;

    try {
      const res = await fetch(`/api/papers/${encodeURIComponent(name)}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("删除失败");
      currentPaperName = null;
      papersDetail.innerHTML = '<div class="detail-placeholder">文档已删除</div>';
      loadPapers();
    } catch (e) {
      alert("删除失败: " + e.message);
    }
  }

  // === Utilities ===
  function esc(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
  }

  function pathBasename(p) {
    if (!p) return "";
    return p.split("/").pop().split("\\").pop();
  }

  // === Public API (for inline onclick handlers) ===
  window.app = {
    viewPaper,
    deletePaper,
    previewImage,
  };

  // === Init ===
  // Load status on page load
  fetch("/api/status")
    .then((r) => r.json())
    .then((s) => {
      document.title = `研究助手 — ${s.model}`;
    })
    .catch(() => {});
})();
