// ---- element references ----
const apiUrl = document.getElementById("apiUrl");
const emailInput = document.getElementById("email");
const slotInput = document.getElementById("slot");
const linesDiv = document.getElementById("lines");
const statusDiv = document.getElementById("status");
const output = document.getElementById("output");

const MAX_LINES = 5; // same limit as OrderIn.lines in main.py

// Fill the email suggestions with the users created by the seed script
const datalist = document.getElementById("seedUsers");
for (let i = 1; i <= 20; i++) {
  datalist.innerHTML += `<option value="student${i}@uni.edu">`;
}
["kitchen", "cashier", "manager", "admin"].forEach((r) => {
  datalist.innerHTML += `<option value="${r}@uni.edu">`;
});

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
// Tabs. Role is guessed from the e-mail prefix of the seed users; the backend still
// enforces roles with 403 (NFR-03). A GET /me endpoint would be the clean way.
// ======================================================================================
const TABS = [
  { id: "order",   label: "Order",     role: "customer", load: () => { loadMenu(); loadSlots(); } },
  { id: "mine",    label: "My orders", role: "customer", load: () => loadMine() },
  { id: "kitchen", label: "Kitchen",   role: "kitchen",  load: () => { loadQueue(); loadWithdraw(); } },
  { id: "cashier", label: "Cashier",   role: "cashier",  load: () => {} },
  { id: "report",  label: "Report",    role: "manager",  load: () => { loadReport(); loadStock(); } },
  { id: "admin",   label: "Admin",     role: "admin",    load: () => {} },
];

function currentRole() {
  const prefix = emailInput.value.split("@")[0].toLowerCase();
  return ["kitchen", "cashier", "manager", "admin"].includes(prefix) ? prefix : "customer";
}
function showTab(id) {
  activeTab = id;
  TABS.forEach((t) => {
    $("tab-" + t.id).hidden = t.id !== id;
    const b = $("t-" + t.id);
    if (b) b.setAttribute("aria-selected", String(t.id === id));
  });
  TABS.find((t) => t.id === id).load();
}
function buildTabs() {
  const role = currentRole();
  $("roleInfo").textContent = role;
  const mine = TABS.filter((t) => t.role === role);
  $("tabs").innerHTML = mine
    .map((t) => `<button type="button" role="tab" id="t-${t.id}" aria-selected="false" data-tab="${t.id}">${esc(t.label)}</button>`)
    .join("");
  showTab(mine[0].id);
}
$("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-tab]");
  if (b) showTab(b.dataset.tab);
});
emailInput.addEventListener("change", buildTabs);

// NEW: customer "My orders" and the kitchen queue refresh themselves every 15 s
setInterval(() => {
  if (document.hidden) return;
  if (activeTab === "mine") loadMine();
  if (activeTab === "kitchen") loadQueue();
}, 15000);

// ======================================================================================
// Screen 1: slots, menu, cart
// ======================================================================================
async function loadSlots() {
  const r = await api("GET", "/slots");
  if (!r.ok) return;
  // Each slot is a button with a fill bar = how full it is (20 orders max, FR-03)
  $("slotBox").innerHTML = r.data.map((s) => {
    const pct = Math.round((s.taken / 20) * 100);
    return `<button type="button" class="slot" data-action="pick-slot" data-id="${esc(s.slot_start)}"
        aria-pressed="false" ${s.bookable ? "" : "disabled"}
        aria-label="${hhmm(s.slot_start)}, ${s.bookable ? s.remaining + " places left" : "not available"}">
        <b>${hhmm(s.slot_start)}</b><small>${s.bookable ? s.remaining + " left" : "closed"}</small>
        <i class="fill"><u style="width:${pct}%"></u></i></button>`;
  }).join("");
  markSlot();
}
// Highlight the slot button that matches the selected time
function markSlot() {
  document.querySelectorAll(".slot").forEach((b) => {
    const on = b.dataset.id.slice(0, 16) === slotInput.value;
    b.classList.toggle("sel", on);
    b.setAttribute("aria-pressed", String(on));
  });
}
slotInput.addEventListener("input", markSlot);

async function loadMenu() {
  const r = await api("GET", "/menu");
  if (!r.ok) return;
  menuCache = {};
  r.data.forEach((i) => (menuCache[i.id] = i));
  $("menuBox").innerHTML = r.data.map((i) => `
    <article class="card dish">
      <h3>${esc(i.name)}</h3>
      <p class="price">${jd(i.price)}</p>
      <p class="tags">${i.tags.split(",").filter(Boolean).map((t) => `<span class="tag">${esc(t.trim())}</span>`).join("")}</p>
      <p class="stock${i.stock <= 5 ? " low" : ""}">${i.stock <= 5 ? "Only " + i.stock + " left" : i.stock + " left"}</p>
      <button type="button" class="wide" data-action="add-item" data-id="${i.id}">Add to order <span data-count="${i.id}"></span></button>
    </article>`).join("") || empty("No items are available right now.");
  renderCart();
}
$("refreshMenu").onclick = () => { loadMenu(); loadSlots(); };

// ---- order lines ----
// Same function name and arguments as before. CHANGED: adding an item that is already in
// the cart raises its quantity (max 5 per line, DB CHECK qty_1_to_5) instead of a new row.
function addLine(itemId = "", qty = 1) {
  const same = [...linesDiv.children].find((r) => r.querySelector(".item").value === String(itemId));
  if (itemId !== "" && same) {
    const q = same.querySelector(".qty");
    q.value = Math.min(5, Number(q.value) + qty);
    renderCart();
    return;
  }
  if (linesDiv.children.length >= MAX_LINES) { toast("An order can hold at most 5 different items.", false); return; }
  const name = menuCache[itemId] ? menuCache[itemId].name : "Item " + itemId;
  const row = document.createElement("div");
  row.className = "line";
  row.innerHTML = `
    <input class="item" type="hidden" value="${esc(itemId)}">
    <span class="nm">${esc(name)}</span>
    <span class="step">
      <button type="button" class="dec ghost" aria-label="Fewer ${esc(name)}">&minus;</button>
      <input class="qty" type="number" min="1" max="5" value="${qty}" aria-label="Quantity of ${esc(name)}">
      <button type="button" class="inc ghost" aria-label="More ${esc(name)}">+</button>
    </span>
    <button type="button" class="remove" aria-label="Remove ${esc(name)}">&times;</button>`;
  const q = row.querySelector(".qty");
  row.querySelector(".dec").onclick = () => { q.value = Math.max(1, Number(q.value) - 1); renderCart(); };
  row.querySelector(".inc").onclick = () => { q.value = Math.min(5, Number(q.value) + 1); renderCart(); };
  q.oninput = renderCart;
  row.querySelector(".remove").onclick = () => { row.remove(); renderCart(); };
  linesDiv.appendChild(row);
  renderCart();
}

// NEW: recompute total, enable/disable the order button, update the badges on the menu cards
function renderCart() {
  let total = 0, count = 0;
  const inCart = {};
  [...linesDiv.children].forEach((row) => {
    const id = row.querySelector(".item").value;
    const q = Number(row.querySelector(".qty").value) || 0;
    if (menuCache[id]) total += menuCache[id].price * q;
    count += q;
    inCart[id] = q;
  });
  const none = linesDiv.children.length === 0;
  $("total").textContent = jd(total);
  $("barTotal").textContent = jd(total);
  $("barText").textContent = count + (count === 1 ? " item" : " items");
  $("empty").hidden = !none;
  $("send").disabled = none;
  document.querySelectorAll("[data-count]").forEach((s) => {
    s.textContent = inCart[s.dataset.count] ? "(" + inCart[s.dataset.count] + ")" : "";
  });
}

// ---- default slot: next 15-minute boundary at least 30 minutes from now ----
function defaultSlot() {
  const d = new Date(Date.now() + 30 * 60 * 1000);
  d.setMinutes(Math.ceil(d.getMinutes() / 15) * 15, 0, 0);
  // datetime-local wants local time "YYYY-MM-DDTHH:mm" (not UTC), so shift by the offset
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}
slotInput.value = defaultSlot();

// ---- send the request ----
document.getElementById("send").onclick = async () => {
  // Build the body exactly as OrderIn expects: { slot_start, lines: [{item_id, quantity}] }
  const lines = [...linesDiv.children].map((row) => ({
    item_id: Number(row.querySelector(".item").value),
    quantity: Number(row.querySelector(".qty").value),
  }));
  const body = {
    slot_start: slotInput.value + ":00", // naive datetime, no timezone (backend uses datetime.now())
    lines: lines,
  };
  const r = await api("POST", "/orders", body, {
    ok: (d) => `Order #${d.order_id} placed. Total ${jd(d.total)}. Your pickup code appears in My orders when it is ready.`,
  });
  if (r.ok) { linesDiv.innerHTML = ""; renderCart(); loadMenu(); loadSlots(); } // refresh stock and slot capacity
};

// ======================================================================================
// Screen 2: my orders (FR-05 cancel, FR-06 pickup code)
// ======================================================================================
const STEPS = ["placed", "preparing", "ready", "collected"];
async function loadMine() {
  const r = await api("GET", "/orders/mine");
  if (!r.ok) return;
  $("mineBox").innerHTML = r.data.map((o) => {
    const idx = STEPS.indexOf(o.state);   // -1 for cancelled / uncollected
    return `<article class="card ord">
      <div class="row"><strong>Order #${o.order_id}</strong>${badge(o.state)}</div>
      <p>${esc(o.slot_start.replace("T", " ").slice(0, 16))} &middot; ${jd(o.total)}</p>
      ${idx >= 0 ? `<ol class="progress">${STEPS.map((s, i) =>
        `<li class="${i <= idx ? "on" : ""}" ${i === idx ? 'aria-current="step"' : ""}>${s}</li>`).join("")}</ol>` : ""}
      ${o.pickup_code ? `<p class="code-l">Pickup code</p><p class="code">${esc(o.pickup_code)}</p>` : ""}
      ${o.state === "placed" ? actBtn("cancel", o.order_id, "Cancel order", "danger") : ""}
    </article>`;
  }).join("") || empty("You have no orders yet.");
}
$("refreshMine").onclick = loadMine;

// ======================================================================================
// Screen 3: kitchen (FR-06 queue, FR-12 withdraw)
// ======================================================================================
async function loadQueue() {
  const r = await api("GET", "/kitchen/queue");
  if (!r.ok) return;
  const groups = {};   // slot time -> orders, so the kitchen sees the rush ahead
  r.data.forEach((o) => (groups[hhmm(o.slot_start)] ||= []).push(o));
  $("queueBox").innerHTML = Object.keys(groups).map((t) => `
    <h3 class="slot-h">${t} <small>${groups[t].length} order${groups[t].length === 1 ? "" : "s"}</small></h3>
    <div class="stack">${groups[t].map((o) => `
      <article class="card ord">
        <div class="row"><strong>#${o.order_id}</strong>${badge(o.state)}</div>
        <ul>${o.items.map((i) => `<li>${esc(i.name)} &times; ${i.quantity}</li>`).join("")}</ul>
        ${o.state === "placed" ? actBtn("preparing", o.order_id, "Start preparing")
          : o.state === "preparing" ? actBtn("ready", o.order_id, "Mark ready") : ""}
      </article>`).join("")}</div>`).join("") || empty("No open orders today.");
}
async function loadWithdraw() {
  const r = await api("GET", "/menu");   // kitchen role sees all items
  if (!r.ok) return;
  $("withdrawBox").innerHTML = r.data.map((i) => i.available
    ? actBtn("withdraw", i.id, "Withdraw " + i.name, "danger")
    : `<span class="tag">${esc(i.name)}: withdrawn</span>`).join("");
}
$("refreshKitchen").onclick = () => { loadQueue(); loadWithdraw(); };

// ======================================================================================
// Screen 4: cashier (FR-07 pickup, FR-13 top-up)
// ======================================================================================
$("pickBtn").onclick = async () => {
  const r = await api("POST", `/orders/${Number($("pickId").value)}/pickup`, { code: $("pickCode").value },
    { ok: "Order handed over." });
  if (r.ok) { $("pickId").value = ""; $("pickCode").value = ""; }
};
$("topBtn").onclick = () => api("POST", "/wallet/topup",
  { customer_email: $("topEmail").value, amount: Number($("topAmount").value) },
  { ok: (d) => "Wallet topped up. New balance: " + jd(d.balance) });

// ======================================================================================
// Screen 5: manager (FR-11 report, FR-02 stock)
// ======================================================================================
$("reportDay").value = new Date().toISOString().slice(0, 10);
async function loadReport() {
  const r = await api("GET", "/reports/daily?day=" + $("reportDay").value);
  if (!r.ok) return;
  const d = r.data;
  const tile = (l, v) => `<div class="tile"><span>${l}</span><strong>${v}</strong></div>`;
  $("reportBox").innerHTML = `<div class="tiles">${tile("Orders", d.orders)}${tile("Collected", d.collected)}
    ${tile("Uncollected", d.uncollected)}${tile("Cancelled", d.cancelled)}${tile("Revenue", jd(d.revenue))}</div>
    <h3>Top items</h3>` + (d.top_items.length
      ? `<ol class="top">${d.top_items.map((t) => `<li>${esc(t.name)} <strong>${t.quantity}</strong></li>`).join("")}</ol>`
      : empty("No items sold on this day."));
}
$("reportBtn").onclick = loadReport;

async function loadStock() {
  const r = await api("GET", "/menu");
  if (!r.ok) return;
  $("stockBox").innerHTML = r.data.map((i) => `
    <div class="card row">
      <label class="inline grow">${esc(i.name)}
        <input id="stock-${i.id}" class="stockIn" type="number" min="0" value="${i.stock}"></label>
      ${actBtn("set-stock", i.id, "Save")}
    </div>`).join("");
}
$("refreshStock").onclick = loadStock;

// ======================================================================================
// Admin (FR-16 audit log, objective 3 manual job trigger)
// ======================================================================================
$("auditBtn").onclick = async () => {
  const a = $("auditAction").value.trim();
  const r = await api("GET", "/audit?limit=100" + (a ? "&action=" + encodeURIComponent(a) : ""));
  if (!r.ok) return;
  $("auditBox").innerHTML = r.data.length
    ? `<table><thead><tr><th scope="col">Time</th><th scope="col">Actor</th><th scope="col">Action</th><th scope="col">Target</th></tr></thead><tbody>` +
      r.data.map((e) => `<tr><td>${esc(e.timestamp.replace("T", " ").slice(0, 19))}</td><td>${e.actor_id}</td><td>${esc(e.action)}</td><td>${esc(e.target)}</td></tr>`).join("") +
      `</tbody></table>`
    : empty("No entries.");
};
$("jobBtn").onclick = () => api("POST", "/admin/run-uncollected-job", null,
  { ok: (d) => d.marked_uncollected + " order(s) marked uncollected." });

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
      if ((await api("POST", `/orders/${id}/cancel`, null, { ok: (d) => "Order cancelled. Refunded " + jd(d.refunded) })).ok) loadMine();
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

buildTabs(); // draw the tabs for the default user