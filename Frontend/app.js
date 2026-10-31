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

// ---- order lines ----
function addLine(itemId = "", qty = 1) {
  if (linesDiv.children.length >= MAX_LINES) return; // backend rejects more than 5
  const row = document.createElement("div");
  row.className = "line";
  row.innerHTML = `
    <input class="item" type="number" min="1" placeholder="item_id" value="${itemId}">
    <input class="qty"  type="number" min="1" placeholder="quantity" value="${qty}">
    <button type="button" class="remove">X</button>`;
  row.querySelector(".remove").onclick = () => row.remove();
  linesDiv.appendChild(row);
}
document.getElementById("addLine").onclick = () => addLine();
addLine(1, 1); // start with one line (item 1, quantity 1)

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

  statusDiv.className = "";
  statusDiv.textContent = "Sending...";
  try {
    const res = await fetch(apiUrl.value + "/orders", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-User-Email": emailInput.value, // read by current_user()
      },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({})); // error responses are JSON too
    statusDiv.textContent = `HTTP ${res.status}`;
    statusDiv.className = res.ok ? "ok" : "err";
    output.textContent =
      "Request:\n" + JSON.stringify(body, null, 2) + "\n\nResponse:\n" + JSON.stringify(data, null, 2);
  } catch (err) {
    // Network error or CORS block (see the CORS note: backend must allow this page's origin)
    statusDiv.textContent = "Request failed";
    statusDiv.className = "err";
    output.textContent = String(err);
  }
};
