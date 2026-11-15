// staff.js: screens of the staff page (staff.html): kitchen, cashier, manager report, admin.
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
// Screen 5: manager (FR-11 report, FR-02 menu and stock)
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
  // CHANGED: each card now edits name, price, tags and stock; withdrawn items get a Re-enable button
  $("stockBox").innerHTML = r.data.map((i) => `
    <div class="card">
      <div class="row"><strong>${esc(i.name)}</strong>
        ${i.available ? "" : '<span class="tag">withdrawn</span>' + actBtn("enable-item", i.id, "Re-enable item")}</div>
      <label>Name <input id="name-${i.id}" type="text" value="${esc(i.name)}"></label>
      <label>Price in fils <input id="price-${i.id}" type="number" min="0" value="${i.price}"></label>
      <label>Tags <input id="tags-${i.id}" type="text" value="${esc(i.tags)}"></label>
      ${actBtn("save-item", i.id, "Save details")}
      <div class="row">
        <label class="inline grow">Stock
          <input id="stock-${i.id}" class="stockIn" type="number" min="0" value="${i.stock}"></label>
        ${actBtn("set-stock", i.id, "Save stock")}
      </div>
    </div>`).join("");
}
$("refreshStock").onclick = loadStock;

// NEW: create a menu item (POST /menu, manager only)
$("newBtn").onclick = async () => {
  const r = await api("POST", "/menu", {
    name: $("newName").value, price: Number($("newPrice").value),
    stock: Number($("newStock").value), tags: $("newTags").value }, { ok: "Item added." });
  if (r.ok) { ["newName", "newPrice", "newStock", "newTags"].forEach((x) => ($(x).value = "")); loadStock(); }
};

// ======================================================================================
// Admin (FR-16 audit log, objective 3 manual job trigger)
// ======================================================================================
$("auditBtn").onclick = async () => {
  const a = $("auditAction").value.trim();
  const r = await api("GET", "/audit?limit=100" + (a ? "&action=" + encodeURIComponent(a) : ""));
  if (!r.ok) return;
  $("auditBox").innerHTML = r.data.length
    ? `<table><thead><tr><th scope="col">Time</th><th scope="col">Actor</th><th scope="col">Action</th><th scope="col">Target</th></tr></thead><tbody>` +
      // CHANGED: actor_id null = the system (scheduled job)
      r.data.map((e) => `<tr><td>${esc(e.timestamp.replace("T", " ").slice(0, 19))}</td><td>${e.actor_id ?? "system"}</td><td>${esc(e.action)}</td><td>${esc(e.target)}</td></tr>`).join("") +
      `</tbody></table>`
    : empty("No entries.");
};
$("jobBtn").onclick = () => api("POST", "/admin/run-uncollected-job", null,
  { ok: (d) => d.marked_uncollected + " order(s) marked uncollected." });