// ======================================================================================
// common.js: loaded by BOTH pages (index.html = customers, staff.html = chefs and staff).
// Holds the request helper, sign-in, tabs and the click handler. Screens live in
// customer.js and staff.js.
// ======================================================================================
// ---- element references (an element is null on the page that does not have it) ----
const apiUrl = document.getElementById("apiUrl");
const emailInput = document.getElementById("email");
const slotInput = document.getElementById("slot");
const linesDiv = document.getElementById("lines");
const statusDiv = document.getElementById("status");
const output = document.getElementById("output");

const MAX_LINES = 5; // same limit as OrderIn.lines in main.py
const PAGE = document.body.dataset.page; // NEW: "customer" or "staff" (set on <body> of each page)

// E-mail suggestions for the sign-in box (users created by the seed script)
const datalist = document.getElementById("seedUsers");
if (PAGE === "customer") {
  for (let i = 1; i <= 20; i++) datalist.innerHTML += `<option value="student${i}@uni.edu">`;
} else {
  ["kitchen", "cashier", "manager", "admin"].forEach((r) => (datalist.innerHTML += `<option value="${r}@uni.edu">`));
}

// ======================================================================================
// Helpers shared by every screen
// ======================================================================================
const $ = (id) => document.getElementById(id);

// Escape database text before it goes into innerHTML (OWASP A03 injection, NFR-04)
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
// Money is stored in fils; show JD with 3 decimals (1 JD = 1000 fils)
const jd = (fils) => (fils / 1000).toFixed(3) + " JD";

let menuCache = {};   // NEW: item id -> item, so the cart can show names and compute the total
let activeTab = "";   // NEW: which tab is open (used by the auto-refresh timer)
let toastTimer;

// NEW: toast = short message in the corner; errors are explained in plain words
function toast(msg, ok) {
  statusDiv.textContent = msg;
  statusDiv.className = "show " + (ok ? "ok" : "err");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (statusDiv.className = ""), 6000);
}

// ONE function that sends every request. opts.ok = success message (text or function(data)).
// GET requests stay silent on success (no "Done." toast every time a list loads).
async function api(method, path, body, opts = {}) {
  try {
    const res = await fetch(apiUrl.value + path, {
      method: method,
      headers: { "Content-Type": "application/json", "X-User-Email": emailInput.value },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({})); // error responses are JSON too
    output.textContent = `${method} ${path} -> HTTP ${res.status}\n` +
      (body ? "\nRequest:\n" + JSON.stringify(body, null, 2) : "") +
      "\n\nResponse:\n" + JSON.stringify(data, null, 2);
    if (!res.ok) {
      const d = data.detail;   // FastAPI: string, or a list for 422 validation errors
      toast(Array.isArray(d) ? d.map((x) => x.msg).join("; ") : d || "Request failed (HTTP " + res.status + ")", false);
    } else if (method !== "GET") {
      toast(typeof opts.ok === "function" ? opts.ok(data) : opts.ok || "Done.", true);
    }
    return { ok: res.ok, status: res.status, data: data };
  } catch (err) {
    // Network error or CORS block (backend must allow this page's origin)
    toast("Cannot reach the server. Is uvicorn running?", false);
    output.textContent = String(err);
    return { ok: false, status: 0, data: null };
  }
}

// Order state is shown as text, not colour only (WCAG 1.4.1)
const badge = (state) => `<span class="badge s-${esc(state)}">${esc(state)}</span>`;
const hhmm = (iso) => iso.slice(11, 16);
const actBtn = (action, id, label, cls = "") =>
  `<button type="button" class="small ${cls}" data-action="${action}" data-id="${esc(id)}">${esc(label)}</button>`;
const empty = (text) => `<p class="hint">${esc(text)}</p>`;


// ======================================================================================
// NEW: accounts. Sign-in is still the simulated SSO (X-User-Email header; no passwords are
// stored, NFR-03), but the page now asks the backend who you are (GET /me), so the role and
// the wallet balance come from the database instead of being guessed from the e-mail.
// ======================================================================================
let me = null; // { id, name, email, role, balance } after sign-in

function renderHeader() {
  $("roleInfo").textContent = me.name + " (" + me.role + ")";
  if ($("balance")) $("balance").textContent = "Wallet " + jd(me.balance);
}
// Re-read the balance (after ordering, cancelling...) and redraw what depends on it
async function refreshMe() {
  const r = await api("GET", "/me");
  if (!r.ok) return;
  me = r.data;
  renderHeader();
  if (linesDiv) renderCart(); // customer page only: the order button depends on the balance
}
async function signIn(email) {
  emailInput.value = email.trim().toLowerCase();
  const r = await api("GET", "/me");
  if (!r.ok) {
    emailInput.value = "";
    sessionStorage.removeItem("cq_email");
    if (r.status === 401) toast("No account with this e-mail.", false);
    return;
  }
  // Each page accepts only its own kind of account
  const isCustomer = r.data.role === "customer";
  if ((PAGE === "customer") !== isCustomer) {
    emailInput.value = "";
    toast(isCustomer ? "This is a customer account. Use the customer page (index.html)."
                     : "This is a staff account. Use the staff page (staff.html).", false);
    return;
  }
  me = r.data;
  sessionStorage.setItem("cq_email", emailInput.value); // survives a page reload, not a closed tab
  $("auth").hidden = true; $("app").hidden = false; $("who").hidden = false;
  renderHeader();
  buildTabs();
}
function signOut() { sessionStorage.removeItem("cq_email"); location.reload(); }
$("inForm").onsubmit = (e) => { e.preventDefault(); signIn($("email").value); };
$("signOut").onclick = signOut;

// ======================================================================================
// Tabs: each role sees only its own screens; the backend still enforces roles with 403 (NFR-03)
// ======================================================================================
const TABS = [
  { id: "order",   label: "Order",     role: "customer", load: () => { loadMenu(); loadSlots(); } },
  { id: "mine",    label: "My orders", role: "customer", load: () => loadMine() },
  { id: "wallet",  label: "Wallet",    role: "customer", load: () => loadWallet() },
  { id: "kitchen", label: "Kitchen",   role: "kitchen",  load: () => { loadQueue(); loadWithdraw(); } },
  { id: "cashier", label: "Cashier",   role: "cashier",  load: () => {} },
  { id: "report",  label: "Report",    role: "manager",  load: () => { loadReport(); loadStock(); } },
  { id: "admin",   label: "Admin",     role: "admin",    load: () => {} },
];

function showTab(id) {
  activeTab = id;
  TABS.forEach((t) => {
    const p = $("tab-" + t.id);          // null on the page that does not have this screen
    if (p) p.hidden = t.id !== id;
    const b = $("t-" + t.id);
    if (b) b.setAttribute("aria-selected", String(t.id === id));
  });
  TABS.find((t) => t.id === id).load();
}
function buildTabs() {
  const mine = TABS.filter((t) => t.role === me.role);
  $("tabs").innerHTML = mine
    .map((t) => `<button type="button" role="tab" id="t-${t.id}" aria-selected="false" data-tab="${t.id}">${esc(t.label)}</button>`)
    .join("");
  showTab(mine[0].id);
}
$("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-tab]");
  if (b) showTab(b.dataset.tab);
});

// Customer "My orders" and the kitchen queue refresh themselves every 15 s
setInterval(() => {
  if (document.hidden || !me) return;
  if (activeTab === "mine") { loadMine(); refreshMe(); }
  if (activeTab === "kitchen") loadQueue();
}, 15000);

// ======================================================================================
// ONE click listener for every button created by the render functions (event delegation)
// ======================================================================================
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-action]");
  if (!b) return;
  const id = b.dataset.id;
  switch (b.dataset.action) {
    case "add-item": addLine(id, 1); break;
    case "pick-slot": slotInput.value = id.slice(0, 16); markSlot(); break;   // "...T10:00:00" -> "...T10:00"
    case "cancel":
      if ((await api("POST", `/orders/${id}/cancel`, null, { ok: (d) => "Order cancelled. Refunded " + jd(d.refunded) })).ok) { loadMine(); refreshMe(); }
      break;
    case "preparing":
    case "ready":
      if ((await api("POST", `/orders/${id}/${b.dataset.action}`, null, { ok: "Order #" + id + " is now " + (b.dataset.action) + "." })).ok) loadQueue();
      break;
    case "withdraw":
      if ((await api("POST", `/menu/${id}/withdraw`, null, { ok: (d) => "Item withdrawn. " + d.cancelled_orders.length + " order(s) refunded." })).ok) { loadWithdraw(); loadQueue(); }
      break;
    case "set-stock":
      if ((await api("PUT", `/menu/${id}/stock`, { stock: Number($("stock-" + id).value) }, { ok: "Stock saved." })).ok) loadStock();
      break;
  }
});


// Come back signed in after a page reload
const savedEmail = sessionStorage.getItem("cq_email");
if (savedEmail) signIn(savedEmail);
