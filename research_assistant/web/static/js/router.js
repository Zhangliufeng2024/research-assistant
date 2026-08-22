/* hash 路由：#/task #/papers #/settings */

const routes = {}; // name → render(root, onCleanup)
let cleanupFn = null;

export function registerRoutes(map) {
  Object.assign(routes, map);
}

function currentRoute() {
  const h = location.hash.replace(/^#\/?/, "").split("/")[0];
  return routes[h] ? h : "task";
}

function apply() {
  const name = currentRoute();
  if (cleanupFn) { try { cleanupFn(); } catch (e) { console.error(e); } cleanupFn = null; }

  document.querySelectorAll("#topnav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === name);
  });

  const main = document.getElementById("main");
  main.innerHTML = "";
  routes[name](main, (fn) => { cleanupFn = fn; });
}

export function initRouter() {
  window.addEventListener("hashchange", apply);
  apply();
}
