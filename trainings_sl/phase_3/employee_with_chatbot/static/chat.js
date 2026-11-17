(() => {
  const MAX_HISTORY = 20;
  const chat = { messages: [], busy: false };
  const el = (id) => document.getElementById(id);
  const panel = el('chat-panel');
  const launcher = el('chat-launcher');
  const list = el('chat-messages');
  const form = el('chat-form');
  const input = el('chat-input');
  const send = el('chat-send');
  const suggestions = el('chat-suggestions');
  const escape = (value) => String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const inline = (value) => escape(value)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>');
  const cells = (row) => row.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());

  function markdown(text) {
    const lines = text.replace(/\r/g, '').split('\n');
    const html = [];
    let paragraph = [];
    const flush = () => { if (paragraph.length) { html.push(`<p>${paragraph.map(inline).join('<br>')}</p>`); paragraph = []; } };
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || '')) {
        flush();
        const head = cells(line);
        const rows = [];
        i += 2;
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
        i--;
        html.push(`<div class="chat-table"><table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
      } else if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
        flush();
        const ordered = /^\s*\d+[.)]/.test(line);
        const items = [];
        while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*•]|\d+[.)])\s+/, ''));
        i--;
        const tag = ordered ? 'ol' : 'ul';
        html.push(`<${tag}>${items.map((item) => `<li>${inline(item)}</li>`).join('')}</${tag}>`);
      } else if (!line.trim()) {
        flush();
      } else {
        paragraph.push(line.replace(/^#{1,6}\s+/, ''));
      }
    }
    flush();
    return html.join('');
  }

  function addBubble(role, content, error = false) {
    const bubble = document.createElement('div');
    bubble.className = `chat-message ${role}${error ? ' error' : ''}`;
    if (role === 'assistant' && !error) bubble.innerHTML = markdown(content);
    else bubble.textContent = content;
    list.append(bubble);
    list.scrollTop = list.scrollHeight;
    return bubble;
  }

  function greet() {
    list.innerHTML = '';
    addBubble('assistant', "Hi! I'm your **People assistant**. Ask me anything about your employees — headcount, salaries, designations, or how to use this app. I can also add, update or delete employees after you confirm.");
    suggestions.hidden = false;
  }

  function setOpen(open) {
    panel.hidden = !open;
    launcher.hidden = open;
    launcher.setAttribute('aria-expanded', String(open));
    if (open) { window.lucide?.createIcons(); input.focus(); }
  }

  async function ask(text) {
    if (chat.busy || !text.trim()) return;
    chat.busy = true;
    send.disabled = true;
    suggestions.hidden = true;
    chat.messages.push({ role: 'user', content: text.trim() });
    addBubble('user', text.trim());
    input.value = '';
    input.style.height = '';
    const typing = addBubble('assistant', '');
    typing.innerHTML = '<span class="chat-typing" aria-label="Assistant is typing"><span></span><span></span><span></span></span>';
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: chat.messages.slice(-MAX_HISTORY) }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const details = data.details?.map((item) => item.msg).join('; ');
        throw new Error(details || data.error || 'The assistant is unavailable right now.');
      }
      typing.remove();
      chat.messages.push({ role: 'assistant', content: data.reply });
      if (data.fallback_used) addBubble('assistant', `Using ${data.model}: the primary model is rate-limited or temporarily unavailable.`);
      addBubble('assistant', data.reply);
      if (data.data_changed) window.dispatchEvent(new Event('employees:changed'));
    } catch (error) {
      typing.remove();
      chat.messages.pop();
      addBubble('assistant', error.message || 'Could not reach the assistant.', true);
    } finally {
      chat.busy = false;
      send.disabled = false;
      input.focus();
    }
  }

  launcher.addEventListener('click', () => setOpen(true));
  el('chat-close').addEventListener('click', () => setOpen(false));
  el('chat-clear').addEventListener('click', () => { if (!chat.busy) { chat.messages = []; greet(); input.focus(); } });
  form.addEventListener('submit', (event) => { event.preventDefault(); ask(input.value); });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); ask(input.value); }
  });
  input.addEventListener('input', () => { input.style.height = ''; input.style.height = `${Math.min(input.scrollHeight, 120)}px`; });
  suggestions.addEventListener('click', (event) => { if (event.target.matches('button')) ask(event.target.textContent); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !panel.hidden && !document.querySelector('dialog[open]')) setOpen(false); });

  greet();
})();
