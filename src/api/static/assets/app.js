// ---- Token management ----
function getToken() {
  return localStorage.getItem("token");
}
function setToken(token) {
  localStorage.setItem("token", token);
}
function clearToken() {
  localStorage.removeItem("token");
}

// ---- Fetch con JWT ----
async function fetchApi(path, options = {}) {
  const token = getToken();
  const headers = { ...(options.headers || {}) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    clearToken();
    window.location.replace("/ui/login.html");
    return null;
  }
  return response;
}

// ---- Auth ----
function requireAuth() {
  if (!getToken()) window.location.replace("/ui/login.html");
}
function logout() {
  clearToken();
  window.location.replace("/ui/login.html");
}

// ---- Tiempo relativo ----
function formatRelativeTime(isoString) {
  if (!isoString) return "nunca";
  const seconds = Math.floor((Date.now() - new Date(isoString)) / 1000);
  if (seconds < 60) return "hace poco";
  if (seconds < 3600) return `hace ${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `hace ${Math.floor(seconds / 3600)}h`;
  return `hace ${Math.floor(seconds / 86400)}d`;
}

// ---- Fecha legible ----
function formatDate(isoString) {
  if (!isoString) return "—";
  return new Date(isoString).toLocaleString("es-VE");
}

// ---- Toast simple ----
function showToast(message, type = "info") {
  const colors = { info: "#2563eb", success: "#16a34a", error: "#dc2626", warning: "#d97706" };
  const el = document.createElement("div");
  el.textContent = message;
  Object.assign(el.style, {
    position: "fixed", bottom: "1.5rem", right: "1.5rem", zIndex: 9999,
    background: colors[type] || colors.info, color: "#fff",
    padding: "0.75rem 1.25rem", borderRadius: "0.5rem",
    fontSize: "0.875rem", boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
    transition: "opacity 0.4s"
  });
  document.body.appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; setTimeout(() => el.remove(), 400); }, 3000);
}

// ---- Navbar: carga nav.html e inyecta en #navbar ----
async function loadNav(activeLink) {
  const el = document.getElementById("navbar");
  if (!el) return;
  const resp = await fetch("/ui/assets/nav.html");
  if (!resp.ok) return;
  el.innerHTML = await resp.text();
  // Marcar link activo
  if (activeLink) {
    el.querySelectorAll("a[data-page]").forEach(a => {
      if (a.dataset.page === activeLink) {
        a.classList.remove("text-white/60");
        a.classList.add("text-white", "font-semibold");
      }
    });
  }
}

// ---- SSE helper ----
function connectSSE(url, onMessage, onError) {
  const es = new EventSource(url);
  es.addEventListener("log", e => { try { onMessage(JSON.parse(e.data)); } catch (_) {} });
  es.addEventListener("keepalive", () => {});
  es.onerror = e => { onError(e); es.close(); };
  return es;
}

// ---- Badge completitud ----
function completitudBadge(pct) {
  if (pct == null) return '<span class="px-2 py-0.5 text-xs rounded-full bg-slate-100 text-slate-500">—</span>';
  const v = Math.round(pct);
  const [bg, txt] = v >= 80 ? ["bg-green-100","text-green-700"] : v >= 50 ? ["bg-yellow-100","text-yellow-700"] : ["bg-red-100","text-red-700"];
  return `<span class="px-2 py-0.5 text-xs rounded-full ${bg} ${txt}">${v}%</span>`;
}

// ---- Badge estado validación ----
function validacionBadge(estado) {
  const map = {
    aprobado:    ["bg-green-100","text-green-700"],
    pendiente:   ["bg-yellow-100","text-yellow-700"],
    rechazado:   ["bg-red-100","text-red-700"],
    requiere_revision: ["bg-orange-100","text-orange-700"],
  };
  const [bg, txt] = map[estado] || ["bg-slate-100","text-slate-500"];
  return `<span class="px-2 py-0.5 text-xs rounded-full ${bg} ${txt}">${estado || "—"}</span>`;
}
