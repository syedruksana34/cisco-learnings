"use strict";
let credentials = null;
let sessionId = null;
let basket = new Map();
const $ = selector => document.querySelector(selector);
const notice = text => {
  $("#auth-notice").textContent = text;
  $("#notice").textContent = text;
  $("#chat-notice").textContent = text;
};

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (credentials) headers.set("Authorization", `Basic ${credentials}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try { message = (await response.json()).message || message; } catch (error) { console.error(error); }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function button(text, fn) {
  const element = node("button", text);
  element.type = "button";
  element.addEventListener("click", () => safe(fn));
  return element;
}

async function safe(fn) {
  try { notice(""); await fn(); } catch (error) { notice(error.message); }
}

async function loadMenu() {
  const [allItems, photos] = await Promise.all([api("/api/menu_items"), api("/static/images/menu/photos.json")]);
  const category = $("#filters").elements.category;
  const selected = category.value;
  const categories = [...new Set(allItems.map(item => item.category))].sort((a, b) => a.localeCompare(b));
  category.replaceChildren(new Option("All categories", ""));
  for (const name of categories) category.append(new Option(name, name));
  if (selected && !categories.includes(selected)) category.append(new Option(`${selected} (no longer available)`, selected));
  category.value = selected;
  const fields = new FormData($("#filters"));
  const keyword = String(fields.get("keyword") || "").trim().toLocaleLowerCase();
  const maxPrice = fields.get("max_price");
  const vegetarian = fields.has("vegetarian");
  const nonvegetarian = fields.has("nonvegetarian");
  const items = allItems.filter(item =>
    (!keyword || item.title.toLocaleLowerCase().includes(keyword)) &&
    (!selected || item.category === selected) &&
    (!maxPrice || Number(item.price) <= Number(maxPrice)) &&
    (vegetarian === nonvegetarian || item.vegetarian === vegetarian));
  const menu = $("#menu"); menu.replaceChildren();
  if (!items.length) menu.append(node("p", "No dishes found. Try a different filter.", "empty-state"));
  for (const item of items) {
    const card = node("article", undefined, "menu-card");
    const artwork = node("div", undefined, "menu-art");
    const photo = photos[item.title];
    if (photo) {
      const image = node("img", undefined, "menu-photo");
      image.src = photo.path;
      image.alt = item.title;
      image.loading = "lazy";
      image.addEventListener("error", () => {
        console.error(`Menu photo could not be loaded: ${photo.path}`);
        image.replaceWith(node("span", "Photo unavailable", "photo-unavailable"));
      });
      artwork.append(image);
    } else {
      artwork.append(node("span", "Photo unavailable", "photo-unavailable"));
    }
    const badge = node("span", undefined, "diet-badge");
    const symbol = node("span", undefined, `diet-symbol ${item.vegetarian ? "veg" : "nonveg"}`);
    symbol.setAttribute("aria-hidden", "true");
    badge.append(symbol, node("span", item.vegetarian ? "VEGETARIAN" : "NON-VEGETARIAN"));
    artwork.append(badge);
    const info = node("div", undefined, "menu-info");
    const footer = node("div", undefined, "menu-footer");
    const add = button("+ Add", () => { const old = basket.get(item.id); basket.set(item.id, { ...item, quantity: (old?.quantity || 0) + 1 }); renderBasket(); });
    add.setAttribute("aria-label", `Add ${item.title} to basket`);
    footer.append(node("strong", `₹${item.price}`), add);
    info.append(node("span", item.category, "menu-category"), node("h3", item.title),
      node("p", `${item.capacity} portions available`, "menu-availability"), footer);
    card.append(artwork, info);
    menu.append(card);
  }
}

function renderBasket() {
  const target = $("#basket"); target.replaceChildren();
  for (const item of basket.values()) {
    const row = node("div", undefined, "basket-row");
    const info = node("div");
    info.append(node("strong", item.title), node("p", `${item.quantity} × ₹${item.price}`));
    const remove = button("Remove", () => { basket.delete(item.id); renderBasket(); });
    remove.setAttribute("aria-label", `Remove ${item.title} from basket`);
    row.append(info, remove);
    target.append(row);
  }
  if (!basket.size) target.append(node("p", "Your basket is empty. Add a dish to get started.", "empty-state"));
}

async function loadOrders() {
  const target = $("#orders"); target.replaceChildren();
  if (!credentials) return;
  const orders = await api("/api/orders");
  if (!orders.length) target.append(node("p", "Your orders will appear here.", "empty-state"));
  for (const order of orders) {
    const row = node("div", undefined, "card order-card");
    row.append(node("strong", `Order #${order.id} · ${order.status}`));
    const items = node("ul", undefined, "order-items");
    for (const item of order.lines) {
      const cancelled = item.cancelled_quantity ? ` · ${item.cancelled_quantity} cancelled` : "";
      items.append(node("li", `${item.title} (${item.category}) · ${item.quantity} × ₹${item.unit_price}${cancelled}`));
    }
    row.append(items, node("p", `Remaining total: ₹${order.remaining_total} (original ₹${order.total})`, "order-total"));
    if (order.status === "CONFIRMED") row.append(button("Cancel", async () => {
      if (!window.confirm(`Cancel all remaining items in order #${order.id}?`)) return;
      await api(`/api/orders/${order.id}/cancel`, { method: "POST" }); await loadOrders(); await loadMenu();
    }));
    const feedback = node("details", undefined, "feedback");
    feedback.append(node("summary", order.feedback ? "Edit your feedback" : "Rate this order"));
    const form = node("form", undefined, "feedback-form");
    const ratingLabel = node("label", "Rating");
    const rating = node("select");
    rating.name = "rating"; rating.required = true;
    rating.append(new Option("Select a rating", ""));
    for (let stars = 1; stars <= 5; stars++) rating.append(new Option(`${stars} ${stars === 1 ? "star" : "stars"}`, stars));
    rating.value = order.feedback ? String(order.feedback.rating) : "";
    ratingLabel.append(rating);
    const commentLabel = node("label", "Your feedback (optional)");
    const comment = node("textarea");
    comment.name = "comment"; comment.maxLength = 1000; comment.rows = 3;
    comment.placeholder = "Tell us about your experience";
    comment.value = order.feedback?.comment || "";
    commentLabel.append(comment);
    const submit = node("button", "Save feedback");
    submit.type = "submit";
    form.append(ratingLabel, commentLabel, node("small", "Your comment is private to you and restaurant admins. Ratings for single-dish orders may be shown as averages, even from one rating."), submit);
    form.addEventListener("submit", event => {
      event.preventDefault();
      safe(async () => {
        submit.disabled = true;
        try {
          await api(`/api/orders/${order.id}/feedback`, {method: "PUT",
            body: JSON.stringify({rating: Number(rating.value), comment: comment.value})});
          await loadOrders();
          notice("Feedback saved. Thank you!");
        } finally { submit.disabled = false; }
      });
    });
    feedback.append(form);
    row.append(feedback);
    target.append(row);
  }
}

async function loadFeedback() {
  const entries = await api("/api/admin/feedback?limit=100");
  const target = $("#admin-feedback"); target.replaceChildren();
  if (!entries.length) target.append(node("p", "No feedback yet.", "empty-state"));
  for (const entry of entries) {
    const card = node("div", undefined, "card");
    card.append(node("strong", `Order #${entry.order_id} · ${entry.username} · ${entry.rating}/5 stars`),
      node("p", entry.comment || "No written feedback."));
    target.append(card);
  }
}

async function loadSessions(selected = sessionId) {
  const select = $("#sessions"); select.replaceChildren(); sessionId = null;
  if (!credentials) { $("#messages").replaceChildren(); $("#pending").replaceChildren(); return; }
  const sessions = await api("/api/chat/sessions");
  select.append(new Option("Select a conversation", ""));
  for (const session of sessions) select.append(new Option(session.title, session.id));
  if (selected && sessions.some(s => s.id === Number(selected))) {
    select.value = String(selected); sessionId = Number(selected); await loadHistory();
  } else { $("#messages").replaceChildren(); $("#pending").replaceChildren(); }
}

async function loadHistory() {
  const target = $("#messages"); target.replaceChildren();
  const messages = [];
  let after = 0, page;
  do {
    page = await api(`/api/chat/sessions/${sessionId}/messages?limit=200&after=${after}`);
    messages.push(...page);
    if (page.length) after = page[page.length - 1].seq_no;
  } while (page.length === 200);
  for (const message of messages) {
    const box = node("div", `${message.role === "user" ? "You" : "Assistant"}: ${message.content}`, `message ${message.role}`);
    if (message.details.fallback_used) box.append(node("p", "A backup AI model answered because the primary model was unavailable."));
    for (const source of message.details.citations || []) box.append(node("p", `Source: ${source.source}, page/section ${source.page} (v${source.version})`));
    target.append(box);
  }
  target.scrollTop = target.scrollHeight;
  await loadPending();
}

function itemDetails(item) {
  const lines = [];
  if (item.id !== undefined) lines.push(`Item ID: ${item.id}`);
  if (item.title !== undefined) lines.push(`Name: ${item.title}`);
  if (item.category !== undefined) lines.push(`Category: ${item.category}`);
  if (item.vegetarian !== undefined) lines.push(`Vegetarian: ${item.vegetarian ? "Yes" : "No"}`);
  if (item.price !== undefined) lines.push(`Price: INR ${item.price}`);
  if (item.capacity !== undefined) lines.push(`Available portions: ${item.capacity}`);
  if (item.active !== undefined) lines.push(`Active: ${item.active ? "Yes" : "No"}`);
  return lines;
}

function orderDetails(order) {
  const lines = [];
  if (order.id !== undefined) lines.push(`Order #${order.id}`);
  if (order.status !== undefined) lines.push(`Status: ${order.status.replaceAll("_", " ")}`);
  if (order.total !== undefined) lines.push(`Total: INR ${order.total}`);
  if (order.created_at !== undefined) lines.push(`Created: ${order.created_at.replace("T", " ")} UTC`);
  if (Array.isArray(order.lines)) {
    lines.push("Items:");
    for (const item of order.lines) {
      lines.push(`• ${item.title || `Item #${item.item_id}`}: ${item.quantity} × INR ${item.unit_price}`);
    }
  }
  return lines;
}

function actionPreview(action) {
  const preview = action.preview;
  const labels = {
    create_order: "Place order", cancel_order: "Cancel order",
    cancel_order_item: "Cancel a dish",
    create_menu_item: "Create menu item", update_menu_item: "Update menu item",
    delete_menu_item: "Disable menu item", update_order_status: "Update order status"
  };
  const lines = [labels[action.action] || "Review action"];
  if (action.action === "create_order" || action.action === "cancel_order") {
    lines.push(...orderDetails(preview));
    if (action.action === "cancel_order") lines.push("This cancels every remaining item in this order.");
  } else if (action.action === "cancel_order_item") {
    lines.push(`Order #${preview.order.id}`, `Dish: ${preview.title}`, `Cancel: ${preview.quantity} × INR ${preview.unit_price}`,
      `Currently remaining: ${preview.remaining_quantity}`, "Other dishes and portions stay in the order.");
  } else if (action.action === "update_order_status") {
    lines.push(...orderDetails(preview.before), `New status: ${preview.after_status.replaceAll("_", " ")}`);
  } else {
    if (preview.before) lines.push("Current details:", ...itemDetails(preview.before));
    if (preview.after) lines.push("New details:", ...itemDetails(preview.after));
  }
  lines.push(`Expires: ${action.expires_at.replace("T", " ")} UTC`);
  return lines.join("\n");
}

async function loadPending() {
  const target = $("#pending"); target.replaceChildren();
  for (const action of await api(`/api/chat/sessions/${sessionId}/actions`)) {
    const box = node("div", `${actionPreview(action)}\n`, "action");
    for (const [label, confirm] of [["Confirm", true], ["Reject", false]]) {
      box.append(button(label, async () => {
        await api(`/api/chat/actions/${action.id}/confirm`, { method: "POST", body: JSON.stringify({ confirm }) });
        await loadHistory(); await loadMenu(); await loadOrders();
      }), " ");
    }
    target.append(box);
  }
}

$("#filters").addEventListener("submit", event => { event.preventDefault(); safe(loadMenu); });
function showAuth(signup) {
  $("#login").hidden = signup;
  $("#signup").hidden = !signup;
  $("#auth-switch").hidden = signup;
  $("#signup-switch").hidden = !signup;
  $("#auth-heading").textContent = signup ? "Join Savour House." : "Welcome back.";
  notice("");
}
$("#show-signup").addEventListener("click", () => showAuth(true));
$("#show-login").addEventListener("click", () => showAuth(false));
$("#signup").addEventListener("submit", event => { event.preventDefault(); safe(async () => {
  const form = event.target, data = new FormData(form);
  if (data.get("password") !== data.get("confirm_password")) throw new Error("Passwords do not match.");
  const user = await api("/api/auth/signup", { method: "POST",
    body: JSON.stringify({ username: data.get("username"), password: data.get("password") }) });
  form.reset();
  showAuth(false);
  $("#login").elements.username.value = user.username;
  notice("Account created. Please sign in.");
  $("#login").elements.password.focus();
}); });
$("#login").addEventListener("submit", event => { event.preventDefault(); safe(async () => {
  const data = new FormData(event.target);
  try { credentials = btoa(`${data.get("username")}:${data.get("password")}`); }
  catch { throw new Error("Username and password must contain printable English characters."); }
  let user;
  try { user = await api("/api/auth/me"); } catch (error) { credentials = null; throw error; }
  $("#identity").textContent = `Hi, ${user.username}!`;
  event.target.elements.password.value = "";
  $("#auth-screen").hidden = true;
  $("#app-screen").hidden = false;
  $("#account-bar").hidden = false;
  $("#admin-panel").hidden = user.role !== "admin";
  await Promise.all([loadMenu(), loadOrders(), loadSessions()]);
}); });
$("#logout").addEventListener("click", () => safe(async () => {
  credentials = null; sessionId = null; basket = new Map(); renderBasket();
  $("#identity").textContent = "";
  $("#auth-screen").hidden = false; $("#app-screen").hidden = true; $("#account-bar").hidden = true;
  $("#admin-panel").hidden = true;
  $("#admin-feedback").replaceChildren();
  $("#chat-panel").hidden = true; $("#chat-toggle").setAttribute("aria-expanded", "false");
  $("#login").reset(); $("#signup").reset(); showAuth(false);
  await loadOrders(); await loadSessions();
}));
$("#chat-toggle").addEventListener("click", () => {
  const panel = $("#chat-panel");
  panel.hidden = !panel.hidden;
  $("#chat-toggle").setAttribute("aria-expanded", String(!panel.hidden));
  if (!panel.hidden) $("#message").focus();
});
$("#chat-close").addEventListener("click", () => {
  $("#chat-panel").hidden = true;
  $("#chat-toggle").setAttribute("aria-expanded", "false");
  $("#chat-toggle").focus();
});
$("#refresh-orders").addEventListener("click", () => safe(loadOrders));
$("#refresh-feedback").addEventListener("click", () => safe(loadFeedback));
$("#order").addEventListener("click", () => safe(async () => {
  if (!credentials || !basket.size) throw new Error("Sign in and add items to your basket.");
  const lines = [...basket.values()].map(item => ({ item_id: item.id, quantity: item.quantity }));
  const order = await api("/api/orders", { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ lines }) });
  basket.clear(); renderBasket(); notice(`Order #${order.id} placed.`); await loadMenu(); await loadOrders();
}));
$("#new-session").addEventListener("click", () => safe(async () => {
  if (!credentials) throw new Error("Sign in first.");
  const session = await api("/api/chat/sessions", { method: "POST" }); await loadSessions(session.id);
}));
$("#sessions").addEventListener("change", event => safe(async () => {
  sessionId = Number(event.target.value) || null;
  if (sessionId) await loadHistory(); else { $("#messages").replaceChildren(); $("#pending").replaceChildren(); }
}));
$("#chat").addEventListener("submit", event => { event.preventDefault(); safe(async () => {
  const input = $("#message"), send = event.target.querySelector("button");
  send.disabled = true; $("#loading").hidden = false;
  try {
    if (!sessionId) {
      const session = await api("/api/chat/sessions", { method: "POST" });
      await loadSessions(session.id);
    }
    await api(`/api/chat/sessions/${sessionId}/messages`, { method: "POST", body: JSON.stringify({ message: input.value }) });
    input.value = ""; await loadSessions(sessionId);
  } catch (error) { if (sessionId) await loadHistory(); throw error; }
  finally { send.disabled = false; $("#loading").hidden = true; }
}); });
$("#admin-item").addEventListener("submit", event => { event.preventDefault(); safe(async () => {
  const data = new FormData(event.target), id = data.get("id"), operation = event.submitter.value;
  if (operation === "update" && !id) throw new Error("Enter an item ID.");
  const item = { title: data.get("title"), category: data.get("category"), price: data.get("price"),
    capacity: Number(data.get("capacity")), vegetarian: data.has("vegetarian"), active: data.has("active") };
  await api(`/api/menu_items${operation === "update" ? `/${Number(id)}` : ""}`,
    { method: operation === "update" ? "PUT" : "POST", body: JSON.stringify(item) });
  await loadMenu(); notice("Menu item saved.");
}); });
$("#disable-item").addEventListener("click", () => safe(async () => {
  const id = Number($("#admin-item").elements.id.value);
  if (!id || !window.confirm(`Disable item #${id}?`)) return;
  await api(`/api/menu_items/${id}`, { method: "DELETE" }); await loadMenu(); notice("Item disabled.");
}));
$("#upload").addEventListener("submit", event => { event.preventDefault(); safe(async () => {
  const result = await api("/api/documents", { method: "POST", body: new FormData(event.target) });
  notice(`Indexed ${result.filename}, version ${result.version}.`);
}); });
$("#status-form").addEventListener("submit", event => { event.preventDefault(); safe(async () => {
  const data = new FormData(event.target);
  await api(`/api/admin/orders/${Number(data.get("id"))}/status`,
    { method: "PATCH", body: JSON.stringify({ status: data.get("status") }) });
  notice("Order status updated."); await loadOrders();
}); });
renderBasket();
