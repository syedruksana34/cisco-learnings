"use strict";

const $ = (selector) => document.querySelector(selector);
const icon = (name, extra = "") => `<svg class="${extra}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const money = (cents) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
const number = (value) => new Intl.NumberFormat("en-US").format(value);
const today = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
};
const field = (key, label, type = "text", options = {}) => ({ key, label, type, ...options });
const departmentField = field("department_id", "Department", "reference", { source: "departments" });
const studentField = field("student_id", "Student", "reference", { source: "students" });
const personFields = [
  field("first_name", "First name"), field("last_name", "Last name"), field("email", "Email address", "email"),
  field("phone_number", "Contact number", "tel", { optional: true, maxlength: 10, pattern: "[0-9]{10}", placeholder: "e.g. 9876543210" }), departmentField,
];
const resources = {
  students: {
    title: "Students", singular: "student", icon: "users", description: "Every student, every step of their academic journey.",
    fields: [field("student_number", "Student ID"), ...personFields, field("year", "Academic year", "number", { min: 1, max: 8, default: 1 }), field("status", "Status", "select", { options: ["Active", "Graduated", "On leave"] })],
    columns: [["Student", "person"], ["Student ID", "student_number"], ["Contact number", "phone_number"], ["Department", "department"], ["Year", "year"], ["Status", "status"]],
  },
  faculty: {
    title: "Faculty", singular: "faculty member", icon: "cap", description: "The people inspiring your campus, all in one place.",
    fields: [field("employee_number", "Employee ID"), ...personFields, field("title", "Academic title")],
    columns: [["Faculty member", "person"], ["Employee ID", "employee_number"], ["Contact number", "phone_number"], ["Department", "department"], ["Title", "title"]],
  },
  departments: {
    title: "Departments", singular: "department", icon: "building", description: "Give every discipline a place to grow.",
    fields: [field("name", "Department name"), field("code", "Department code")],
    columns: [["Department", "name"], ["Code", "code"], ["Students", "student_count"], ["Courses", "course_count"]],
  },
  courses: {
    title: "Courses", singular: "course", icon: "book", description: "Shape your curriculum and connect learning with possibility.",
    fields: [field("code", "Course code"), field("name", "Course name"), departmentField, field("faculty_id", "Instructor", "reference", { source: "faculty", optional: true }), field("credits", "Credits", "number", { min: 1, max: 12, default: 3 }), field("capacity", "Seats per semester", "number", { min: 1, max: 1000, default: 40 })],
    columns: [["Code", "code"], ["Course", "name"], ["Department", "department"], ["Instructor", "instructor"], ["Credits", "credits"], ["Capacity", "capacity"]],
  },
  enrollments: {
    title: "Enrollments", singular: "enrollment", icon: "book", description: "Connect students to courses and keep every semester on track.",
    fields: [studentField, field("course_id", "Course", "reference", { source: "courses" }), field("semester", "Semester", "text", { placeholder: "e.g. Fall 2026" }), field("status", "Status", "select", { options: ["Enrolled", "Completed", "Dropped"] })],
    columns: [["Student", "student"], ["Student ID", "student_number"], ["Course", "course"], ["Semester", "semester"], ["Status", "status"]],
  },
  attendance: {
    title: "Attendance", singular: "attendance record", icon: "check", description: "A simple way to keep up with who is showing up.",
    fields: [field("enrollment_id", "Student & course enrollment", "reference", { source: "enrollments" }), field("date", "Class date", "date", { default: today, max: today }), field("status", "Attendance status", "select", { options: ["Present", "Absent", "Late", "Excused"] })],
    columns: [["Student", "student"], ["Course", "course"], ["Semester", "semester"], ["Date", "date"], ["Status", "status"]],
  },
  fees: {
    title: "Fees & payments", singular: "fee", icon: "wallet", description: "Clear balances, timely payments, and fewer loose ends.",
    fields: [studentField, field("description", "Fee description"), field("amount_cents", "Total amount (USD)", "money", { min: "0.01" }), field("paid_cents", "Amount paid (USD)", "money", { min: "0", default: "0.00" }), field("due_date", "Due date", "date")],
    columns: [["Student", "student"], ["Description", "description"], ["Total", "amount_cents"], ["Paid", "paid_cents"], ["Balance", "balance_cents"], ["Due date", "due_date"], ["Status", "fee_status"]],
  },
};

let csrfToken = "";
let user = null;
let currentPage = "dashboard";
let records = [];
let lookup = {};
let page = 1;
let editingId = null;
let loadVersion = 0;
let toastTimer;
const pageSize = 8;
let chatVersion = 0;
let chatPending = false;
let chatHistory = [];
let chatDocumentId = null;
let signupMode = false;

function setSignupMode(enabled) {
  signupMode = enabled;
  $("#auth-title").textContent = enabled ? "Create your account." : "Welcome back.";
  $("#auth-description").textContent = enabled ? "Join your local university workspace." : "Sign in to your university workspace.";
  $("#auth-submit-label").textContent = enabled ? "Create account" : "Sign in to workspace";
  $("#confirm-password-field").hidden = !enabled;
  $("#confirm-password").disabled = !enabled;
  $("#confirm-password").required = enabled;
  $("#confirm-password").value = "";
  $("#password").value = "";
  $("#password").minLength = enabled ? 12 : 0;
  $("#password").autocomplete = enabled ? "new-password" : "current-password";
  $("#login-error").textContent = "";
  if ($("#auth-switch")) {
    $("#auth-switch").textContent = enabled ? "Sign in instead" : "Create an account";
    $("#auth-switch-hint").textContent = enabled ? "Already have an account?" : "New to CampusFlow?";
    $("#signup-notice").hidden = !enabled;
  }
}

async function api(path, options = {}) {
  const response = await fetch(`/api/${path}`, {
    ...options,
    headers: { ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }), "X-CSRF-Token": csrfToken, ...options.headers },
  });
  if (response.status === 204) return null;
  const body = await response.json();
  if (!response.ok) {
    if (response.status === 401 && user) {
      user = null;
      const state = await api("session");
      csrfToken = state.csrf_token;
      showSession();
    }
    throw new Error(body.error || "The request failed. Please try again.");
  }
  return body;
}

function toast(message, error = false) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").classList.toggle("error", error);
  $("#toast").hidden = false;
  toastTimer = setTimeout(() => { $("#toast").hidden = true; }, 4500);
}

function showSession() {
  $("#boot").hidden = true;
  $("#login-screen").hidden = Boolean(user);
  $("#app").hidden = !user;
  $("#campus-assistant").hidden = !user;
  if (!user) { resetChat(); setSignupMode(false); }
  if (!user && $("#record-dialog").open) $("#record-dialog").close();
  if (user) {
    $("#profile-name").textContent = user.username;
    $("#profile-avatar").textContent = user.username.slice(0, 1).toUpperCase();
  }
}

function resetChat() {
  chatVersion++;
  chatPending = false;
  chatHistory = [];
  chatDocumentId = null;
  $("#chat-messages").replaceChildren();
  $("#chat-input").value = "";
  $("#chat-input").disabled = false;
  $("#chat-send").disabled = false;
  $("#chat-status").textContent = "";
  $("#chat-panel").hidden = true;
  $("#chat-toggle").setAttribute("aria-expanded", "false");
  setKnowledgeOpen(false);
  $("#knowledge-form").reset();
  $("#knowledge-list").replaceChildren();
  $("#knowledge-preview").textContent = "";
  $("#knowledge-preview").hidden = true;
}

function chatMessage(text, sender, links = [], sources = []) {
  const message = document.createElement("div");
  message.className = `chat-message ${sender}`;
  const label = document.createElement("strong");
  label.textContent = sender === "user" ? "You" : sender === "error" ? "Request failed" : "Campus assistant";
  const content = document.createElement("p");
  content.textContent = text;
  message.append(label, content);
  if (sources.length) {
    const heading = document.createElement("strong");
    heading.textContent = "Retrieved sources (expand to verify)";
    message.append(heading);
    for (const source of sources) {
      const details = document.createElement("details");
      details.className = "chat-source";
      const summary = document.createElement("summary");
      summary.textContent = `[${source.number}] ${source.title}${source.page ? ` — page ${source.page}` : ""}`;
      const excerpt = document.createElement("p");
      excerpt.textContent = source.excerpt;
      details.append(summary, excerpt);
      message.append(details);
    }
  }
  if (links.length) {
    const shortcuts = document.createElement("div");
    shortcuts.className = "chat-links";
    for (const link of links) {
      if (link.page !== "dashboard" && !Object.hasOwn(resources, link.page)) continue;
      const anchor = document.createElement("a");
      anchor.href = `#${link.page}`;
      anchor.textContent = link.label;
      anchor.addEventListener("click", closeChat);
      shortcuts.append(anchor);
    }
    message.append(shortcuts);
  }
  const messages = $("#chat-messages");
  messages.append(message);
  while (messages.children.length > 40) messages.firstElementChild.remove();
  messages.scrollTop = messages.scrollHeight;
}

function closeChat() {
  $("#chat-panel").hidden = true;
  $("#chat-toggle").setAttribute("aria-expanded", "false");
  $("#chat-toggle").focus();
}

function setKnowledgeOpen(open) {
  $("#knowledge-panel").hidden = !open;
  $("#knowledge-open").setAttribute("aria-expanded", String(open));
  $("#chat-messages").hidden = open;
  $(".chat-suggestions").hidden = open;
}

async function sendChat(message) {
  if (!user || chatPending) return;
  message = message.trim();
  if (!message || message.length > 500) return;
  setKnowledgeOpen(false);
  chatPending = true;
  const version = chatVersion;
  const documentId = chatDocumentId;
  chatMessage(message, "user");
  $("#chat-input").value = "";
  $("#chat-input").disabled = true;
  $("#chat-send").disabled = true;
  $("#chat-status").textContent = "Checking your campus...";
  try {
    const body = $("#chat-panel").dataset.mode === "rag"
      ? { message, history: chatHistory, document_id: documentId } : { message };
    const response = await api("chatbot", { method: "POST", body: JSON.stringify(body) });
    if (version !== chatVersion || !user) return;
    chatMessage(response.reply, "assistant", response.links, response.sources);
    if (response.mode === "rag") {
      if (chatDocumentId === documentId) chatDocumentId = response.document_id ?? null;
      chatHistory.push({ role: "user", content: message }, { role: "assistant", content: response.reply });
      chatHistory = chatHistory.slice(-6);
    }
  } catch (error) {
    if (version !== chatVersion || !user) return;
    chatMessage(`${error.message} Your question has been restored below; you can send it again.`, "error");
    $("#chat-input").value = message;
  } finally {
    if (version === chatVersion) {
      chatPending = false;
      $("#chat-input").disabled = false;
      $("#chat-send").disabled = false;
      $("#chat-status").textContent = "";
      if (!$("#chat-panel").hidden && $("#knowledge-panel").hidden) $("#chat-input").focus();
    }
  }
}

async function loadKnowledge() {
  const version = chatVersion;
  const response = await api("knowledge");
  if (!user || version !== chatVersion) return;
  $("#knowledge-mode").textContent = response.mode === "rag"
    ? `Generation model: ${response.model}. Local lexical retrieval with source citations.`
    : "Rule-based mode is enabled. Set RAG_ENABLED=1 and restart Django to use this library in chat.";
  $("#knowledge-list").innerHTML = response.data.length ? response.data.map((doc) =>
    `<article class="knowledge-item"><div><strong>${escapeHTML(doc.title)}</strong><p>${escapeHTML(doc.filename || "Entered text")} · ${doc.chunk_count} chunks</p></div><div><button type="button" class="btn secondary small-btn" data-knowledge-view="${doc.id}">View</button> <button type="button" class="btn secondary small-btn" data-knowledge-delete="${doc.id}">Remove</button></div></article>`
  ).join("") : "<p>No sources yet. Add your first campus policy above.</p>";
}

$("#knowledge-open").addEventListener("click", async () => {
  const open = $("#knowledge-panel").hidden;
  setKnowledgeOpen(open);
  if (!open) { $("#chat-input").focus(); return; }
  const version = chatVersion;
  $("#knowledge-name").focus();
  $("#knowledge-error").textContent = "";
  $("#knowledge-list").textContent = "Loading sources...";
  try { await loadKnowledge(); }
  catch (error) {
    if (user && version === chatVersion) $("#knowledge-error").textContent = error.message;
  }
});
$("#knowledge-close").addEventListener("click", () => {
  setKnowledgeOpen(false);
  $("#chat-input").focus();
});
$("#knowledge-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const version = chatVersion;
  $("#knowledge-error").textContent = "";
  const title = $("#knowledge-name").value.trim();
  const text = $("#knowledge-text").value.trim();
  const file = $("#knowledge-file").files[0];
  if ((!text && !file) || (text && file)) {
    $("#knowledge-error").textContent = "Enter text or choose a file, not both.";
    return;
  }
  if (file && file.size > 5 * 1024 * 1024) {
    $("#knowledge-error").textContent = "Files must be 5 MB or smaller.";
    return;
  }
  let body;
  if (file) {
    body = new FormData();
    body.append("title", title);
    body.append("file", file);
  } else body = JSON.stringify({ title, text });
  $("#knowledge-save").disabled = true;
  $("#knowledge-save").textContent = file ? "Reading file locally..." : "Adding knowledge...";
  try {
    const response = await api("knowledge", { method: "POST", body });
    if (!user || version !== chatVersion) return;
    chatDocumentId = response.data.id;
    $("#knowledge-form").reset();
    await loadKnowledge();
    if (!user || version !== chatVersion) return;
    chatMessage(`Added "${title}" to the shared knowledge library. Say "summarize" or ask a question about it.`, "assistant");
    setKnowledgeOpen(false);
    if (!$("#chat-panel").hidden && !chatPending) $("#chat-input").focus();
  } catch (error) {
    if (user && version === chatVersion) $("#knowledge-error").textContent = error.message;
  } finally {
    $("#knowledge-save").disabled = false;
    $("#knowledge-save").textContent = "Add knowledge";
  }
});
$("#knowledge-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const version = chatVersion;
  $("#knowledge-error").textContent = "";
  button.disabled = true;
  try {
    if (button.dataset.knowledgeDelete) {
      if (!confirm("Remove this source from future answers? Existing chat messages will still display it until cleared.")) return;
      await api(`knowledge/${button.dataset.knowledgeDelete}`, { method: "DELETE" });
      if (!user || version !== chatVersion) return;
      if (chatDocumentId === Number(button.dataset.knowledgeDelete)) chatDocumentId = null;
      $("#knowledge-preview").hidden = true;
      $("#knowledge-preview").textContent = "";
      await loadKnowledge();
    } else {
      const response = await api(`knowledge/${button.dataset.knowledgeView}`);
      if (!user || version !== chatVersion) return;
      $("#knowledge-preview").textContent = `${response.data.title}\n\n${response.data.chunks.map((part) => `${part.page ? `Page ${part.page}\n` : ""}${part.text}`).join("\n\n")}`;
      $("#knowledge-preview").hidden = false;
    }
  } catch (error) {
    if (user && version === chatVersion) $("#knowledge-error").textContent = error.message;
  } finally { button.disabled = false; }
});

function badge(status) {
  const tone = ["Absent", "Overdue", "Dropped"].includes(status) ? "danger" : ["Late", "On leave", "Pending", "Partial"].includes(status) ? "warning" : ["Excused", "Completed", "Graduated"].includes(status) ? "neutral" : "";
  return `<span class="badge ${tone}">${escapeHTML(status)}</span>`;
}

function feeStatus(row) {
  if (row.paid_cents >= row.amount_cents) return "Paid";
  if (row.due_date < today()) return "Overdue";
  return row.paid_cents > 0 ? "Partial" : "Pending";
}

function person(row, index = 0) {
  const name = `${row.first_name} ${row.last_name}`;
  const colors = ["", "blue", "gold", "purple"];
  return `<div class="person"><span class="avatar ${colors[index % 4]}">${escapeHTML(row.first_name.slice(0, 1) + row.last_name.slice(0, 1))}</span><div><strong>${escapeHTML(name)}</strong><small>${escapeHTML(row.email)}</small></div></div>`;
}

function statCard(label, value, note, glyph, tone = "") {
  return `<div class="stat-card"><div class="stat-top"><span class="stat-label">${label}</span><span class="stat-icon ${tone}">${icon(glyph)}</span></div><div class="stat-value">${value}</div><p class="stat-note">${note}</p></div>`;
}

function renderDashboard(data) {
  const counts = data.counts;
  const finance = data.finance;
  const attendance = data.attendance.total ? `${Math.round(data.attendance.attended / data.attendance.total * 100)}%` : "\u2014";
  const collectionRate = finance.total_cents ? Math.round(finance.paid_cents / finance.total_cents * 100) : 0;
  const distribution = data.departments.map((dept) => `
    <div class="distribution-row"><div class="distribution-label"><span>${escapeHTML(dept.name)}</span><strong>${number(dept.count)}</strong></div><progress value="${dept.count}" max="${Math.max(counts.students, 1)}" aria-label="${escapeHTML(dept.name)} student distribution"></progress></div>`).join("");
  $("#dashboard-view").innerHTML = `
    <div class="welcome-banner"><div><h2>Good to see you, ${escapeHTML(user.username)}.</h2><p>A thriving campus starts with a clear picture. Here is what is happening across your university.</p></div><div class="banner-art">${icon("cap")}</div></div>
    <div class="stats-grid">
      ${statCard("Total students", number(counts.students), `<span>${counts.departments} departments</span> across campus`, "users")}
      ${statCard("Faculty members", number(counts.faculty), "Supporting learning, every day", "cap", "blue")}
      ${statCard("Courses offered", number(counts.courses), `<span>${counts.enrollments} enrollments</span> across semesters`, "book", "gold")}
      ${statCard("Attendance rate", attendance, "Present + late / all recorded classes", "check", "purple")}
    </div>
    <div class="dashboard-columns">
      <section class="panel"><div class="panel-heading"><div><h2>Recently added students</h2><p>The latest additions to your campus community</p></div><a class="text-link" href="#students">View all ${icon("arrow")}</a></div>
        <div class="table-scroll"><table><thead><tr><th>Student</th><th>Department</th><th>Status</th></tr></thead><tbody>${data.recent_students.map((row, i) => `<tr><td>${person(row, i)}</td><td>${escapeHTML(row.department)}</td><td>${badge(row.status)}</td></tr>`).join("") || '<tr><td colspan="3">No students yet. Add your first student to get started.</td></tr>'}</tbody></table></div>
      </section>
      <section class="panel"><div class="panel-heading"><div><h2>Students by department</h2><p>A campus made of many disciplines</p></div>${icon("building")}</div><div class="distribution">${distribution || '<p class="muted small">Add departments to see the distribution.</p>'}<div class="distribution-footer"><span class="live-dot"></span> ${number(counts.students)} students across ${counts.departments} departments</div></div></section>
    </div>
    <div class="dashboard-columns">
      <section class="panel"><div class="panel-heading"><div><h2>Outstanding fees</h2><p>Unpaid balances, earliest due first</p></div><a class="text-link" href="#fees">Manage fees ${icon("arrow")}</a></div><div class="fee-list">
        ${data.outstanding_fees.map((row) => `<div class="fee-item"><div><strong>${escapeHTML(row.student)}</strong><small>${escapeHTML(row.description)} &middot; Due ${escapeHTML(row.due_date)}</small></div><div class="fee-amount">${money(row.amount_cents - row.paid_cents)}<small>${badge(feeStatus(row))}</small></div></div>`).join("") || '<div class="empty-state"><h3>All caught up.</h3><p class="muted">There are no outstanding fees.</p></div>'}
      </div></section>
      <section class="panel"><div class="panel-heading"><div><h2>Fee collection</h2><p>All recorded fees, in one clear view</p></div>${icon("wallet")}</div><div class="finance-overview"><div class="finance-total">${money(finance.paid_cents)} <small>collected</small></div><p class="small muted">${collectionRate}% of ${money(finance.total_cents)} total fees</p><progress value="${finance.paid_cents}" max="${Math.max(finance.total_cents, 1)}" aria-label="Fee collection progress"></progress><div class="finance-legend"><div>Collected<strong>${money(finance.paid_cents)}</strong></div><div>Outstanding<strong>${money(finance.total_cents - finance.paid_cents)}</strong></div></div><div class="panel-note">A little clarity goes a long way. Keep payment records up to date for an accurate financial picture.</div></div></section>
    </div>
    <div class="quick-links">
      <button class="quick-link" data-quick="students">${icon("users")}<span><strong>Add a student</strong><small>Welcome someone new to campus</small></span>${icon("arrow", "arrow")}</button>
      <button class="quick-link" data-quick="attendance">${icon("check")}<span><strong>Record attendance</strong><small>Keep academic participation in view</small></span>${icon("arrow", "arrow")}</button>
      <button class="quick-link" data-quick="fees">${icon("wallet")}<span><strong>Create a fee record</strong><small>Bring your campus finances together</small></span>${icon("arrow", "arrow")}</button>
    </div>`;
  $$("[data-quick]").forEach((button) => button.addEventListener("click", async () => {
    const target = button.dataset.quick;
    location.hash = target;
    try { await openForm(target); } catch (error) { toast(error.message, true); }
  }));
}

function $$(selector) { return [...document.querySelectorAll(selector)]; }

async function loadPage() {
  if (!user) return;
  const version = ++loadVersion;
  const hash = location.hash.slice(1);
  currentPage = Object.hasOwn(resources, hash) ? hash : "dashboard";
  const dashboard = currentPage === "dashboard";
  const meta = resources[currentPage];
  $("#sidebar").classList.remove("open");
  $("#menu-toggle").setAttribute("aria-expanded", "false");
  $$("nav a").forEach((link) => {
    const active = link.dataset.page === currentPage;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("#page-error").hidden = true;
  $("#breadcrumb-page").textContent = dashboard ? "Overview" : meta.title;
  $("#page-eyebrow").textContent = dashboard ? "YOUR CAMPUS AT A GLANCE" : "YOUR CONNECTED CAMPUS";
  $("#page-title").textContent = dashboard ? "Campus overview" : meta.title;
  $("#page-description").textContent = dashboard ? "A clear view of your people, progress, and day-to-day operations." : meta.description;
  $("#dashboard-view").hidden = !dashboard;
  $("#records-view").hidden = dashboard;
  $("#heading-actions").innerHTML = dashboard
    ? `<span class="date-label">${icon("check")}${escapeHTML(new Date().toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" }))}</span><button class="btn primary" id="add-record">${icon("plus")} Add student</button>`
    : `<button class="btn secondary" id="export-records">${icon("download")} Export all CSV</button><button class="btn primary" id="add-record">${icon("plus")} Add ${meta.singular}</button>`;
  $("#add-record").addEventListener("click", () => openForm(dashboard ? "students" : currentPage).catch((error) => toast(error.message, true)));
  if (!dashboard) $("#export-records").addEventListener("click", () => { window.location.href = `/api/export/${currentPage}`; });
  $("#search").value = "";
  page = 1;
  if (dashboard) $("#dashboard-view").textContent = "Loading campus overview...";
  else {
    records = [];
    setFilter();
    renderTable();
    $("#table-body").innerHTML = '<tr><td>Loading records...</td></tr>';
    $("#empty-state").hidden = true;
    $("#resource-summary").textContent = "";
  }
  try {
    const target = currentPage;
    const [result, summary] = await Promise.all([api(target), dashboard ? Promise.resolve(null) : api("dashboard")]);
    if (version !== loadVersion || !user) return;
    const dashboardData = dashboard ? result : summary;
    $("#student-nav-count").textContent = number(dashboardData.counts.students);
    if (dashboard) renderDashboard(result);
    else {
      records = result.data;
      $("#table-title").textContent = `All ${meta.title.toLowerCase()}`;
      setFilter();
      renderSummary();
      renderTable();
    }
  } catch (error) {
    if (version !== loadVersion) return;
    if (dashboard) $("#dashboard-view").textContent = "";
    else { records = []; renderTable(); }
    $("#page-error").textContent = error.message;
    const retry = document.createElement("button");
    retry.className = "btn secondary small-btn";
    retry.textContent = "Retry";
    retry.addEventListener("click", loadPage);
    $("#page-error").append(retry);
    $("#page-error").hidden = false;
  }
}

function setFilter() {
  const key = ["students", "faculty", "courses"].includes(currentPage) ? "department" : ["attendance", "enrollments"].includes(currentPage) ? "status" : currentPage === "fees" ? "fee_status" : null;
  const select = $("#record-filter");
  select.hidden = !key;
  select.dataset.field = key || "";
  const options = key ? [...new Set(records.map((row) => key === "fee_status" ? feeStatus(row) : row[key]))].sort() : [];
  select.innerHTML = `<option value="">All ${key === "department" ? "departments" : "statuses"}</option>${options.map((value) => `<option>${escapeHTML(value)}</option>`).join("")}`;
}

function renderSummary() {
  const chips = [["Total records", number(records.length)]];
  if (currentPage === "fees") {
    chips.push(["Total billed", money(records.reduce((sum, row) => sum + row.amount_cents, 0))], ["Outstanding", money(records.reduce((sum, row) => sum + row.balance_cents, 0))], ["Overdue", records.filter((row) => feeStatus(row) === "Overdue").length]);
  } else if (currentPage === "students") chips.push(["Active students", records.filter((row) => row.status === "Active").length]);
  else if (currentPage === "attendance") chips.push(["Present or late", records.filter((row) => ["Present", "Late"].includes(row.status)).length]);
  else if (currentPage === "enrollments") chips.push(["Currently enrolled", records.filter((row) => row.status === "Enrolled").length]);
  $("#resource-summary").innerHTML = chips.map(([label, value]) => `<span class="summary-chip">${label}<strong>${value}</strong></span>`).join("");
}

function renderTable() {
  const meta = resources[currentPage];
  if (!meta) return;
  const query = $("#search").value.trim().toLowerCase();
  const filter = $("#record-filter").value;
  const filterKey = $("#record-filter").dataset.field;
  const filtered = records.filter((row) => Object.values(row).some((value) => String(value ?? "").toLowerCase().includes(query)) && (!filter || (filterKey === "fee_status" ? feeStatus(row) : row[filterKey]) === filter));
  const maxPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  page = Math.min(page, maxPages);
  const start = (page - 1) * pageSize;
  const shown = filtered.slice(start, start + pageSize);
  $("#table-head").innerHTML = `<tr>${meta.columns.map(([label]) => `<th scope="col">${label}</th>`).join("")}<th scope="col">Actions</th></tr>`;
  $("#table-body").innerHTML = shown.map((row, index) => `<tr>${meta.columns.map(([, key]) => {
    let value;
    if (key === "person") value = person(row, index);
    else if (key === "status") value = badge(row.status);
    else if (key === "fee_status") value = badge(feeStatus(row));
    else if (key.endsWith("_cents")) value = money(row[key]);
    else value = escapeHTML(key === "phone_number" && !row[key] ? "\u2014" : row[key]);
    return `<td>${value}</td>`;
  }).join("")}<td><div class="row-actions"><button class="icon-button" data-edit="${row.id}" aria-label="Edit ${escapeHTML(meta.singular)} ${row.id}">${icon("edit")}</button><button class="icon-button delete" data-delete="${row.id}" aria-label="Delete ${escapeHTML(meta.singular)} ${row.id}">${icon("trash")}</button></div></td></tr>`).join("");
  $("#record-count").textContent = `${number(filtered.length)} ${filtered.length === 1 ? "record" : "records"}${query || filter ? " matching filters" : " in your workspace"}`;
  $("#empty-state").hidden = filtered.length !== 0;
  $("#pagination-info").textContent = filtered.length ? `Showing ${start + 1}\u2013${Math.min(start + pageSize, filtered.length)} of ${number(filtered.length)} records` : "No records to display";
  $("#previous-page").disabled = page <= 1;
  $("#next-page").disabled = page >= maxPages;
  $$("[data-edit]").forEach((button) => button.addEventListener("click", () => openForm(currentPage, Number(button.dataset.edit)).catch((error) => toast(error.message, true))));
  $$("[data-delete]").forEach((button) => button.addEventListener("click", () => deleteRecord(Number(button.dataset.delete), button)));
}

function referenceLabel(source, row) {
  if (["students", "faculty"].includes(source)) return `${row.first_name} ${row.last_name} (${row.student_number || row.employee_number})`;
  if (source === "courses") return `${row.code} \u00b7 ${row.name}`;
  if (source === "enrollments") return `${row.student} \u00b7 ${row.course} \u00b7 ${row.semester} (${row.status})`;
  return row.name;
}

async function openForm(resource, id = null) {
  const meta = resources[resource];
  const row = id ? records.find((item) => item.id === id) : null;
  if (id && !row) throw new Error("This record is no longer available. Reload the page.");
  const sources = [...new Set(meta.fields.filter((item) => item.source).map((item) => item.source))];
  const results = await Promise.all(sources.map((source) => api(source)));
  if (!user) return;
  lookup = Object.fromEntries(sources.map((source, i) => [source, results[i].data]));
  editingId = id;
  $("#record-form").dataset.resource = resource;
  $("#dialog-title").textContent = `${id ? "Edit" : "Add"} ${meta.singular}`;
  $("#record-error").textContent = "";
  $("#save-record").disabled = false;
  $("#form-fields").innerHTML = meta.fields.map((item) => {
    const defaultValue = typeof item.default === "function" ? item.default() : item.default;
    let value = row ? row[item.key] : (defaultValue ?? "");
    if (item.type === "money" && row) value = (value / 100).toFixed(2);
    let input;
    const required = item.optional ? "" : "required";
    if (["reference", "select"].includes(item.type)) {
      const options = item.type === "reference"
        ? lookup[item.source].map((record) => ({ value: record.id, label: referenceLabel(item.source, record) }))
        : item.options.map((option) => ({ value: option, label: option }));
      input = `<select id="field-${item.key}" name="${item.key}" ${required}>${item.type === "reference" ? `<option value="">${item.optional ? "Unassigned" : "Select an option"}</option>` : ""}${options.map((option) => `<option value="${escapeHTML(option.value)}" ${String(value) === String(option.value) ? "selected" : ""}>${escapeHTML(option.label)}</option>`).join("")}</select>`;
      if (item.type === "reference" && !options.length) input += `<small>No ${item.source} available. Create one first.</small>`;
    } else {
      const type = item.type === "money" ? "number" : item.type;
      const max = typeof item.max === "function" ? item.max() : item.max;
      const pattern = item.pattern ? `pattern="${item.pattern}" inputmode="numeric"` : "";
      input = `<input id="field-${item.key}" name="${item.key}" type="${type}" value="${escapeHTML(value)}" ${required} ${pattern} ${item.min !== undefined ? `min="${item.min}"` : ""} ${max !== undefined ? `max="${max}"` : ""} ${item.type === "money" ? 'step="0.01" max="21474836.47"' : item.type === "number" ? 'step="1"' : `maxlength="${item.maxlength || 200}"`} placeholder="${escapeHTML(item.placeholder || "")}">`;
      if (item.pattern) input += '<small>Exactly 10 digits; no spaces or country code.</small>';
    }
    return `<div class="form-field"><label for="field-${item.key}">${item.label}${item.optional ? " (optional)" : ""}</label>${input}</div>`;
  }).join("");
  $("#record-dialog").showModal();
}

async function saveRecord(event) {
  event.preventDefault();
  const resource = event.currentTarget.dataset.resource;
  const values = new FormData(event.currentTarget);
  const data = {};
  for (const item of resources[resource].fields) {
    const value = values.get(item.key);
    if (item.type === "reference") data[item.key] = value ? Number(value) : null;
    else if (item.type === "number") data[item.key] = Number(value);
    else if (item.type === "money") data[item.key] = Math.round(Number(value) * 100);
    else data[item.key] = value;
  }
  $("#save-record").disabled = true;
  $("#record-error").textContent = "";
  try {
    await api(`${resource}${editingId ? `/${editingId}` : ""}`, { method: editingId ? "PUT" : "POST", body: JSON.stringify(data) });
    $("#record-dialog").close();
    toast(`${resources[resource].singular[0].toUpperCase() + resources[resource].singular.slice(1)} ${editingId ? "updated" : "created"} successfully.`);
    await loadPage();
  } catch (error) {
    $("#record-error").textContent = error.message;
  } finally {
    $("#save-record").disabled = false;
  }
}

async function deleteRecord(id, button) {
  const resource = currentPage;
  if (!window.confirm(`Permanently delete this ${resources[resource].singular}? Linked records must be removed or reassigned first. This cannot be undone.`)) return;
  button.disabled = true;
  try {
    await api(`${resource}/${id}`, { method: "DELETE" });
    toast("Record deleted.");
    await loadPage();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#auth-submit");
  button.disabled = true;
  if ($("#auth-switch")) $("#auth-switch").disabled = true;
  $("#login-error").textContent = "";
  try {
    const data = { username: $("#username").value, password: $("#password").value };
    if (signupMode) data.confirm_password = $("#confirm-password").value;
    const state = await api(signupMode ? "signup" : "login", { method: "POST", body: JSON.stringify(data) });
    user = state.user;
    csrfToken = state.csrf_token;
    $("#password").value = "";
    $("#confirm-password").value = "";
    showSession();
    await loadPage();
  } catch (error) {
    $("#login-error").textContent = error.message;
  } finally {
    button.disabled = false;
    if ($("#auth-switch")) $("#auth-switch").disabled = false;
  }
});
if ($("#auth-switch")) $("#auth-switch").addEventListener("click", () => { setSignupMode(!signupMode); $("#username").focus(); });
$("#logout").addEventListener("click", async () => {
  try {
    await api("logout", { method: "POST" });
    user = null;
    loadVersion++;
    const state = await api("session");
    csrfToken = state.csrf_token;
    showSession();
  } catch (error) { toast(error.message, true); }
});
$("#record-form").addEventListener("submit", saveRecord);
$("#chat-toggle").addEventListener("click", () => {
  if (!$("#chat-panel").hidden) { closeChat(); return; }
  $("#chat-panel").hidden = false;
  $("#chat-toggle").setAttribute("aria-expanded", "true");
  if (!$("#chat-messages").children.length) chatMessage($("#chat-panel").dataset.mode === "rag"
    ? "Hello! I use local Ollama to answer from campus knowledge and live aggregate statistics. Select Upload / knowledge above to add documents, images, recordings, text, or code right here, then ask a question. Expand the retrieved sources to check my answer; AI can make mistakes. I cannot change records or access individual student/faculty details."
    : "Hello! I am a local rule-based assistant. Ask about campus counts, attendance, fees, or workflows. I cannot change records.", "assistant");
  $("#chat-input").focus();
});
$("#chat-close").addEventListener("click", closeChat);
$("#chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  sendChat($("#chat-input").value);
});
$$("[data-chat-prompt]").forEach((button) => button.addEventListener("click", () => sendChat(button.dataset.chatPrompt)));
$("#close-dialog").addEventListener("click", () => $("#record-dialog").close());
$("#cancel-dialog").addEventListener("click", () => $("#record-dialog").close());
$("#search").addEventListener("input", () => { page = 1; renderTable(); });
$("#record-filter").addEventListener("change", () => { page = 1; renderTable(); });
$("#previous-page").addEventListener("click", () => { page--; renderTable(); });
$("#next-page").addEventListener("click", () => { page++; renderTable(); });
$("#menu-toggle").addEventListener("click", () => {
  const open = $("#sidebar").classList.toggle("open");
  $("#menu-toggle").setAttribute("aria-expanded", String(open));
});
document.addEventListener("click", (event) => {
  if (!$("#sidebar").contains(event.target) && !$("#menu-toggle").contains(event.target)) {
    $("#sidebar").classList.remove("open");
    $("#menu-toggle").setAttribute("aria-expanded", "false");
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (!$("#chat-panel").hidden && !$("#knowledge-panel").hidden) {
      setKnowledgeOpen(false);
      $("#knowledge-open").focus();
    } else if (!$("#chat-panel").hidden) closeChat();
    $("#sidebar").classList.remove("open");
    $("#menu-toggle").setAttribute("aria-expanded", "false");
  }
});
window.addEventListener("hashchange", loadPage);
(async function boot() {
  try {
    const state = await api("session");
    user = state.user;
    csrfToken = state.csrf_token;
    showSession();
    await loadPage();
  } catch (error) {
    $("#boot").hidden = true;
    $("#login-screen").hidden = false;
    $("#login-error").textContent = `Could not connect: ${error.message}. Reload to retry.`;
  }
})();
