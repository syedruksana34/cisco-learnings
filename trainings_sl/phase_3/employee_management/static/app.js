const state = { employees: [], editingId: null, salaryId: null, confirmAction: null, loadError: false };
const $ = (selector) => document.querySelector(selector);
const icons = () => window.lucide?.createIcons();
const money = (value) => new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
  const data = await response.json();
  if (!response.ok) {
    const details = data.details?.map((item) => `${item.loc.at(-1)}: ${item.msg}`).join('; ');
    throw new Error(details || data.error || 'Something went wrong.');
  }
  return data;
}

let toastTimer;
function notify(message, error = false) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.className = `toast visible${error ? ' error' : ''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.className = 'toast'; }, 3500);
}

async function loadEmployees() {
  try {
    const response = await fetch('/getAllEmployees');
    const data = await response.json();
    if (!response.ok && !(response.status === 404 && data.error === 'No Employees Available')) throw new Error(data.error || 'Could not load employees.');
    state.employees = response.ok ? data : [];
    state.loadError = false;
  } catch (error) {
    state.loadError = true;
    notify(error.message || 'Could not connect to the server.', true);
  }
  render();
}

function render() {
  const employees = state.employees;
  const query = $('#search').value.trim().toLowerCase();
  const filtered = employees.filter((employee) => [employee.id, employee.name, employee.desig].some((value) => String(value).toLowerCase().includes(query)));
  $('#nav-count').textContent = employees.length;
  $('#total-count').textContent = employees.length;
  $('#designation-count').textContent = new Set(employees.map((employee) => employee.desig.toLowerCase())).size;
  $('#average-salary').textContent = employees.length ? money(employees.reduce((total, employee) => total + employee.salary, 0) / employees.length) : '—';
  $('#directory-count').textContent = employees.length;
  $('#result-count').textContent = `${filtered.length} ${filtered.length === 1 ? 'employee' : 'employees'}`;
  $('#footer-count').textContent = `Showing ${filtered.length} of ${employees.length} ${employees.length === 1 ? 'employee' : 'employees'}`;
  $('#delete-all').disabled = !employees.length || state.loadError;
  $('#employee-rows').innerHTML = filtered.map((employee) => {
    const initials = employee.name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase();
    return `<tr><td><div class="person-cell"><span class="avatar">${escapeHtml(initials)}</span><span>${escapeHtml(employee.name)}</span></div></td><td>#${employee.id}</td><td><span class="role-tag">${escapeHtml(employee.desig)}</span></td><td>${employee.age}</td><td>${money(employee.salary)}</td><td><div class="actions"><button class="icon-button" data-action="edit" data-id="${employee.id}" title="Edit employee" aria-label="Edit ${escapeHtml(employee.name)}"><i data-lucide="pencil"></i></button><button class="icon-button" data-action="salary" data-id="${employee.id}" title="Update salary" aria-label="Update salary for ${escapeHtml(employee.name)}"><i data-lucide="wallet"></i></button><button class="icon-button delete" data-action="delete" data-id="${employee.id}" title="Delete employee" aria-label="Delete ${escapeHtml(employee.name)}"><i data-lucide="trash-2"></i></button></div></td></tr>`;
  }).join('');
  const empty = $('#empty-state');
  empty.hidden = filtered.length > 0;
  $('#empty-title').textContent = state.loadError ? 'Unable to load employees' : query ? 'No employees found' : 'Your directory is empty';
  $('#empty-description').textContent = state.loadError ? 'Check your connection and refresh the directory.' : query ? 'Try a different search term.' : 'Add your first employee to get started.';
  $('#empty-add').hidden = Boolean(query) || state.loadError;
  icons();
}

function openEmployee(employee = null) {
  const form = $('#employee-form');
  form.reset();
  state.editingId = employee?.id ?? null;
  $('#form-error').textContent = '';
  $('#dialog-title').textContent = employee ? 'Edit employee' : 'Add employee';
  $('#dialog-description').textContent = employee ? 'Update the details for this employee.' : 'Add a person to your directory.';
  $('#save-button').textContent = employee ? 'Save changes' : 'Add employee';
  form.elements.id.disabled = Boolean(employee);
  if (employee) for (const key of ['id', 'name', 'age', 'desig', 'salary']) form.elements[key].value = employee[key];
  $('#employee-dialog').showModal();
}

$('#add-button').addEventListener('click', () => openEmployee());
$('#empty-add').addEventListener('click', () => openEmployee());
$('#refresh').addEventListener('click', loadEmployees);
$('#search').addEventListener('input', render);
document.addEventListener('keydown', (event) => {
  if (event.key === '/' && !document.querySelector('dialog[open]') && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) { event.preventDefault(); $('#search').focus(); }
});
document.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', () => document.getElementById(button.dataset.close).close()));

$('#employee-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const employee = { id: Number(form.elements.id.value), name: form.elements.name.value.trim(), age: Number(form.elements.age.value), salary: Number(form.elements.salary.value), desig: form.elements.desig.value.trim() };
  const editing = state.editingId !== null;
  const submit = $('#save-button');
  submit.disabled = true;
  try {
    await request(editing ? `/updateEmployee/${state.editingId}` : '/addEmployee', { method: editing ? 'PUT' : 'POST', body: JSON.stringify(employee) });
    $('#employee-dialog').close();
    await loadEmployees();
    notify(editing ? 'Employee updated.' : 'Employee added.');
  } catch (error) { $('#form-error').textContent = error.message; }
  finally { submit.disabled = false; }
});

$('#employee-rows').addEventListener('click', (event) => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const employee = state.employees.find((item) => item.id === Number(button.dataset.id));
  if (!employee) return;
  if (button.dataset.action === 'edit') openEmployee(employee);
  if (button.dataset.action === 'salary') {
    state.salaryId = employee.id;
    $('#salary-description').textContent = `Update compensation for ${employee.name}.`;
    $('#salary-form').elements.salary.value = employee.salary;
    $('#salary-error').textContent = '';
    $('#salary-dialog').showModal();
  }
  if (button.dataset.action === 'delete') confirmDelete(`Delete ${employee.name}?`, 'This employee will be removed from your directory. This cannot be undone.', `/deleteEmployee/${employee.id}`);
});

$('#salary-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = event.currentTarget.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    await request(`/updateSalary/${state.salaryId}`, { method: 'PATCH', body: JSON.stringify({ salary: Number(event.currentTarget.elements.salary.value) }) });
    $('#salary-dialog').close();
    await loadEmployees();
    notify('Salary updated.');
  } catch (error) { $('#salary-error').textContent = error.message; }
  finally { submit.disabled = false; }
});

function confirmDelete(title, description, path) {
  $('#confirm-title').textContent = title;
  $('#confirm-description').textContent = description;
  $('#confirm-error').textContent = '';
  state.confirmAction = path;
  $('#confirm-dialog').showModal();
}
$('#delete-all').addEventListener('click', () => confirmDelete('Delete all employees?', 'Every employee will be removed from your directory. This cannot be undone.', '/deleteAllEmployees'));
$('#confirm-action').addEventListener('click', async (event) => {
  event.currentTarget.disabled = true;
  try {
    await request(state.confirmAction, { method: 'DELETE' });
    $('#confirm-dialog').close();
    await loadEmployees();
    notify('Employee directory updated.');
  } catch (error) { $('#confirm-error').textContent = error.message; }
  finally { event.currentTarget.disabled = false; }
});

icons();
loadEmployees();