const form = document.querySelector('#chat-form');
const input = document.querySelector('#message-input');
const sendButton = document.querySelector('#send-button');
const clearButton = document.querySelector('#clear-chat');
const messagesElement = document.querySelector('#messages');
const welcome = document.querySelector('#welcome');
const statusElement = document.querySelector('#status');

let conversation = [];

function addMessage(role, content) {
  const message = document.createElement('article');
  message.className = `message ${role}`;
  const label = document.createElement('span');
  label.className = 'message-label';
  label.textContent = role === 'user' ? 'You' : 'Assistant';
  const body = document.createElement('p');
  body.textContent = content;
  message.append(label, body);
  messagesElement.append(message);
  return message;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!content || sendButton.disabled) return;

  const userMessage = { role: 'user', content };
  const nextConversation = [...conversation, userMessage];
  const userBubble = addMessage('user', content);
  welcome.hidden = true;
  statusElement.textContent = 'Thinking…';
  sendButton.disabled = true;
  input.disabled = true;
  clearButton.disabled = true;

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: nextConversation }),
    });
    const body = await response.text();
    let data;
    try {
      data = JSON.parse(body);
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
      throw new Error(`The server returned an invalid response (HTTP ${response.status}). Check the server logs.`);
    }
    if (!response.ok) {
      throw new Error(typeof data.detail === 'string' ? data.detail : `The request failed (HTTP ${response.status}).`);
    }
    if (typeof data.reply !== 'string' || !data.reply.trim()) {
      throw new Error('The server returned an empty response.');
    }

    conversation = [...nextConversation, { role: 'assistant', content: data.reply }];
    addMessage('assistant', data.reply);
    input.value = '';
    statusElement.textContent = '';
  } catch (error) {
    userBubble.remove();
    welcome.hidden = messagesElement.childElementCount > 0;
    statusElement.textContent = error.message || 'Could not connect to the server.';
    statusElement.classList.add('error');
  } finally {
    sendButton.disabled = false;
    input.disabled = false;
    clearButton.disabled = false;
    input.focus();
  }
});

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
});

input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

clearButton.addEventListener('click', () => {
  conversation = [];
  messagesElement.replaceChildren();
  welcome.hidden = false;
  statusElement.textContent = '';
  statusElement.classList.remove('error');
  input.value = '';
  input.focus();
});

form.addEventListener('submit', () => {
  statusElement.classList.remove('error');
});
