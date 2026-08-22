/* 工作区文件树（懒加载单层展开）：依赖 R1 的 GET /api/workspace/tree。
 * 后端未上线时面板显示提示文案，不抛错——前端先行、后端落地即通。
 */
import { api } from "../api.js";
import { el } from "../format.js";

function iconFor(nd) {
  if (nd.type === "dir") return "▸";
  const n = (nd.name || "").toLowerCase();
  if (/\.(png|jpe?g|gif|svg|webp)$/.test(n)) return "▣";
  if (/\.(docx?|pdf|tex)$/.test(n)) return "▤";
  if (/\.(csv|xlsx|json)$/.test(n)) return "▦";
  if (/\.(py|js|mjs|ts)$/.test(n)) return "◈";
  if (/\.(md|txt|bib|log)$/.test(n)) return "▬";
  return "▪";
}

export function createFileTree(container, { onOpen } = {}) {
  container.classList.add("ft-tree");

  async function loadChildren(path, slot, depth) {
    try {
      const res = await api.get(`/api/workspace/tree?path=${encodeURIComponent(path)}&depth=1`);
      const items = res.items || res.children || [];
      slot.innerHTML = "";
      if (!items.length && depth === 0) {
        slot.append(el("div", { class: "empty", style: "padding:12px" }, "工作区为空"));
        return;
      }
      for (const nd of items) slot.append(row(nd, depth));
    } catch (e) {
      slot.innerHTML = "";
      const notReady = /not found|404/i.test(e.message || "");
      slot.append(el("div", { class: "empty", style: "padding:12px" },
        notReady ? "工作区 API 未就绪（R1 后端待部署）" : `加载失败：${e.message}`));
    }
  }

  function row(nd, depth) {
    const r = el("div", {
      class: `ft-row ${nd.type}`,
      style: `padding-left:${8 + depth * 14}px`,
    });
    r.append(
      el("span", { class: "ft-icon" }, iconFor(nd)),
      el("span", { class: "ft-name", title: nd.path }, nd.name));

    if (nd.type === "dir") {
      const kidSlot = el("div", { class: "ft-kids" });
      let open = false;
      r.addEventListener("click", () => {
        open = !open;
        r.classList.toggle("open", open);
        if (open && !kidSlot.dataset.loaded) {
          kidSlot.dataset.loaded = "1";
          loadChildren(nd.path, kidSlot, depth + 1);
        }
        kidSlot.style.display = open ? "" : "none";
      });
      const wrap = el("div", {});
      wrap.append(r, kidSlot);
      return wrap;
    }

    r.addEventListener("click", () => onOpen && onOpen(nd));
    return r;
  }

  loadChildren("", container, 0);

  return {
    refresh() {
      container.innerHTML = "";
      loadChildren("", container, 0);
    },
  };
}
