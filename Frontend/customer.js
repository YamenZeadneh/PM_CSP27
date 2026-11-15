// customer.js: screens of the customer page (index.html): order, my orders, wallet, sign-up.
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
// Adding an item that is already in the cart raises its quantity (max 5 per line,
// DB CHECK qty_1_to_5) instead of a new row.
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

// recompute total, enable/disable the order button, update the badges on the menu cards
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
  const short = !!me && total > me.balance;   // the wallet cannot cover this order
  $("short").hidden = !short;
  $("send").disabled = none || short || isBlocked();   // CHANGED: a blocked customer cannot press Place order (FR-09)
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
  if (r.ok) { linesDiv.innerHTML = ""; renderCart(); refreshMe(); loadMenu(); loadSlots(); } // refresh stock and slot capacity
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
      ${o.state === "placed"
        ? (new Date(o.slot_start) - Date.now() >= 15 * 60 * 1000          // CHANGED: same 15-minute rule as the server
            ? actBtn("cancel", o.order_id, "Cancel order", "danger")
            : '<p class="hint">Cancellation closed (15 minutes before the slot).</p>')
        : ""}
    </article>`;
  }).join("") || empty("You have no orders yet.");
}
$("refreshMine").onclick = loadMine;


// ======================================================================================
// wallet screen (balance + last 30 ledger rows from GET /wallet/history)
// ======================================================================================
async function loadWallet() {
  const r = await api("GET", "/wallet/history");
  if (!r.ok) return;
  $("walletBox").innerHTML =
    `<div class="tile"><span>Balance</span><strong>${jd(r.data.balance)}</strong></div>` +
    (r.data.transactions.length
      ? `<ul class="tx">${r.data.transactions.map((t) => `<li>
          <span>${esc(t.reference === "signup" ? "Opening balance" : t.kind)}<small>${esc(t.time.replace("T", " ").slice(0, 16))}</small></span>
          <strong>${t.amount > 0 ? "+" : ""}${jd(t.amount)}</strong></li>`).join("")}</ul>`
      : empty("No transactions yet."));
}
$("refreshWallet").onclick = loadWallet;

// ======================================================================================
// create an account. The customer chooses the opening wallet balance in JD;
// the page converts it to fils (integer money, constraint in 29.3.5).
// ======================================================================================
$("showIn").onclick = () => { $("inForm").hidden = false; $("upForm").hidden = true; };
$("showUp").onclick = () => { $("inForm").hidden = true; $("upForm").hidden = false; };
document.querySelectorAll("[data-amt]").forEach((b) => (b.onclick = () => { $("suBalance").value = b.dataset.amt; }));

$("upForm").onsubmit = async (e) => {
  e.preventDefault();
  const amount = parseFloat($("suBalance").value || "0");
  if (!(amount >= 0)) { toast("Choose a starting balance of 0 JD or more.", false); return; }
  const email = $("suEmail").value.trim().toLowerCase();
  const r = await api("POST", "/signup",
    { name: $("suName").value, email: email, initial_balance: Math.round(amount * 1000) },
    { ok: (d) => "Account created. Opening balance " + jd(d.balance) + "." });
  if (r.ok) signIn(email); // go straight into the app
};