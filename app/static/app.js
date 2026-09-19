/**
 * CalAI - Frontend Application Logic
 * Handles auth, chat sessions, messaging, and markdown rendering.
 */

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  token: null,
  user: null,
  currentSessionId: null,
  isLoading: false,
  sidebarOpen: true,
};

// ── API ────────────────────────────────────────────────────────────────────
const api = {
  baseUrl: window.location.origin,

  async request(method, path, body = null) {
    const headers = { 'Content-Type': 'application/json' };
    if (state.token) headers['Authorization'] = `Bearer ${state.token}`;

    const resp = await fetch(`${api.baseUrl}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : null,
    });

    if (resp.status === 401) {
      clearAuth();
      throw new Error('Session expired. Please log in again.');
    }

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: { message: 'Request failed' } }));
      throw new Error(err.detail?.message || 'Something went wrong');
    }

    return resp.status === 204 ? null : resp.json();
  },

  get: (path) => api.request('GET', path),
  post: (path, body) => api.request('POST', path, body),
  delete: (path) => api.request('DELETE', path),
};

// ── Auth ───────────────────────────────────────────────────────────────────
function loginWithGoogle() {
  window.location.href = '/auth/login';
}

function clearAuth() {
  localStorage.removeItem('cal_token');
  localStorage.removeItem('cal_user');
  state.token = null;
  state.user = null;
  const adminBtn = document.getElementById('admin-dashboard-btn');
  if (adminBtn) adminBtn.remove();
  showLoginOverlay();
}

async function logout() {
  try { await api.post('/auth/logout'); } catch (_) {}
  clearAuth();
}

function showLoginOverlay() {
  document.getElementById('login-overlay').classList.remove('hidden');
  document.getElementById('app').classList.add('hidden');
}

function showApp() {
  document.getElementById('login-overlay').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
}

async function handleAuthCallback() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get('access_token') || null;

  // After OAuth, the callback redirects back to / with the token in the URL
  // We check localStorage first (if already logged in)
  const storedToken = localStorage.getItem('cal_token');

  if (storedToken) {
    state.token = storedToken;
    try {
      const user = await api.get('/auth/me');
      state.user = user;
      localStorage.setItem('cal_user', JSON.stringify(user));
      renderUserInfo();
      showApp();
      loadSessions();
      return;
    } catch (_) {
      localStorage.removeItem('cal_token');
    }
  }

  showLoginOverlay();
}

// ── User Info ──────────────────────────────────────────────────────────────
function renderUserInfo() {
  const user = state.user;
  if (!user) return;
  document.getElementById('user-name').textContent = user.name || 'User';
  document.getElementById('user-email').textContent = user.email || '';
  const avatar = document.getElementById('user-avatar');
  if (user.picture_url) {
    avatar.src = user.picture_url;
    avatar.onerror = () => { avatar.src = ''; avatar.textContent = '👤'; };
  }

  // Dynamic Admin Dashboard button: only rendered if verified as admin
  const headerActions = document.getElementById('header-actions');
  let adminBtn = document.getElementById('admin-dashboard-btn');

  if (user.is_admin) {
    if (!adminBtn && headerActions) {
      adminBtn = document.createElement('a');
      adminBtn.id = 'admin-dashboard-btn';
      adminBtn.href = '/admin';
      adminBtn.className = 'admin-link-btn';
      adminBtn.title = 'Open Admin Dashboard';
      adminBtn.innerHTML = '<span>⚙️</span><span>Admin Dashboard</span>';
      headerActions.appendChild(adminBtn);
    }
  } else if (adminBtn) {
    adminBtn.remove();
  }
}

// ── Sessions ───────────────────────────────────────────────────────────────
async function loadSessions() {
  try {
    const sessions = await api.get('/agent/sessions');
    renderSessions(sessions);
  } catch (err) {
    console.error('Failed to load sessions:', err);
  }
}

function renderSessions(sessions) {
  const container = document.getElementById('sessions-list');
  if (!container) return;
  container.innerHTML = '<div class="sessions-label">Recent Chats</div>';

  if (!sessions || !sessions.length) {
    const empty = document.createElement('div');
    empty.className = 'sessions-label';
    empty.style.marginTop = '1rem';
    empty.textContent = 'No chats yet';
    container.appendChild(empty);
    return;
  }

  sessions.forEach(session => {
    const item = document.createElement('div');
    item.className = `session-item ${session.id === state.currentSessionId ? 'active' : ''}`;
    item.dataset.sessionId = session.id;
    item.innerHTML = `
      <span class="session-icon">💬</span>
      <span class="session-title" title="${escapeHtml(session.title)}">${escapeHtml(session.title)}</span>
      <button class="session-delete-btn" title="Delete chat" onclick="deleteSessionFromSidebar(event, '${session.id}')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"></polyline>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>
      </button>
    `;
    item.onclick = (e) => {
      if (e.target.closest('.session-delete-btn')) return;
      loadSession(session.id, session.title);
    };
    container.appendChild(item);
  });
}

async function loadSession(sessionId, title) {
  state.currentSessionId = sessionId;
  document.getElementById('chat-title').textContent = title || 'Chat';

  const clearBtn = document.getElementById('clear-chat-btn');
  if (clearBtn) clearBtn.classList.remove('hidden');

  // Clear messages
  const container = document.getElementById('messages-container');
  container.innerHTML = '';

  // Update sidebar active state
  document.querySelectorAll('.session-item').forEach(el => {
    el.classList.toggle('active', el.dataset.sessionId === sessionId);
  });

  try {
    const messages = await api.get(`/agent/sessions/${sessionId}`);
    messages.forEach(msg => appendMessage(msg.role, msg.content, msg.id));
    scrollToBottom();
  } catch (err) {
    showError('Failed to load messages.');
  }
}

function startNewChat() {
  state.currentSessionId = null;
  document.getElementById('chat-title').textContent = 'New Chat';

  const clearBtn = document.getElementById('clear-chat-btn');
  if (clearBtn) clearBtn.classList.add('hidden');

  const container = document.getElementById('messages-container');
  container.innerHTML = '';

  // Re-show welcome state
  const welcome = createWelcomeState();
  container.appendChild(welcome);

  // Clear active session
  document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
  document.getElementById('message-input').focus();
}

function createWelcomeState() {
  const div = document.createElement('div');
  div.className = 'welcome-state';
  div.id = 'welcome-state';
  div.innerHTML = `
    <div class="welcome-icon">📅</div>
    <h2 class="welcome-title">How can I help with your calendar?</h2>
    <p class="welcome-sub">Ask me anything about your schedule</p>
    <div class="quick-actions">
      <button class="quick-btn" onclick="sendQuick('What do I have scheduled this week?')">📆 This week's schedule</button>
      <button class="quick-btn" onclick="sendQuick('Schedule a meeting tomorrow at 10am for 1 hour')">➕ Schedule a meeting</button>
      <button class="quick-btn" onclick="sendQuick('Find me a free 1-hour slot today')">🕐 Find free time today</button>
      <button class="quick-btn" onclick="sendQuick('What events do I have next Monday?')">📋 Check next Monday</button>
    </div>
  `;
  return div;
}

// ── Messaging ──────────────────────────────────────────────────────────────
async function sendMessage() {
  const input = document.getElementById('message-input');
  const message = input.value.trim();
  if (!message || state.isLoading) return;

  // Hide welcome state
  const welcome = document.getElementById('welcome-state');
  if (welcome) welcome.remove();

  // Show user message
  const userMsgEl = appendMessage('user', message);
  input.value = '';
  autoResize(input);

  // Show typing indicator
  const typingEl = showTyping();
  state.isLoading = true;
  setSendDisabled(true);

  try {
    const resp = await api.post('/agent/chat', {
      message,
      session_id: state.currentSessionId,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });

    state.currentSessionId = resp.session_id;
    document.getElementById('chat-title').textContent = resp.session_title;

    const clearBtn = document.getElementById('clear-chat-btn');
    if (clearBtn) clearBtn.classList.remove('hidden');

    if (resp.user_message_id && userMsgEl) {
      attachDeleteButtonToMessage(userMsgEl, resp.user_message_id);
    }

    typingEl.remove();
    appendMessage('assistant', resp.reply, resp.assistant_message_id);
    await loadSessions();

  } catch (err) {
    typingEl.remove();
    appendMessage('assistant', `❌ ${err.message || 'Something went wrong. Please try again.'}`);
  } finally {
    state.isLoading = false;
    setSendDisabled(false);
    scrollToBottom();
  }
}

function sendQuick(text) {
  document.getElementById('message-input').value = text;
  sendMessage();
}

function appendMessage(role, content, messageId = null) {
  const container = document.getElementById('messages-container');

  const user = state.user;
  const avatarContent = role === 'user'
    ? (user?.name?.[0]?.toUpperCase() || '👤')
    : '📅';

  const div = document.createElement('div');
  div.className = `message ${role}`;
  if (messageId) div.dataset.messageId = messageId;

  const deleteBtnHtml = messageId ? `
    <button class="msg-delete-btn" title="Delete message" onclick="deleteMessageById('${messageId}', this)">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="3 6 5 6 21 6"></polyline>
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
      </svg>
    </button>
  ` : '';

  div.innerHTML = `
    <div class="message-avatar">${avatarContent}</div>
    <div class="message-wrapper">
      <div class="message-bubble">${renderMarkdown(content)}</div>
      ${deleteBtnHtml}
    </div>
  `;
  container.appendChild(div);
  scrollToBottom();
  return div;
}

function attachDeleteButtonToMessage(div, messageId) {
  if (!div || !messageId || div.querySelector('.msg-delete-btn')) return;
  div.dataset.messageId = messageId;
  const wrapper = div.querySelector('.message-wrapper') || div.querySelector('.message-bubble');
  if (wrapper) {
    const btn = document.createElement('button');
    btn.className = 'msg-delete-btn';
    btn.title = 'Delete message';
    btn.innerHTML = `
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="3 6 5 6 21 6"></polyline>
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
      </svg>
    `;
    btn.onclick = () => deleteMessageById(messageId, btn);
    wrapper.appendChild(btn);
  }
}

// ── Production Toast Notifications ───────────────────────────────────────────
function showToast(message, type = 'info', duration = 3500) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const icons = {
    success: '✓',
    error: '✕',
    warning: '⚠️',
    info: 'ℹ️',
  };

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icons[type] || 'ℹ️'}</span>
    <span class="toast-message">${escapeHtml(message)}</span>
    <button class="toast-close" onclick="this.parentElement.remove()">×</button>
  `;

  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('show'));

  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 250);
  }, duration);
}

// ── Production Confirmation Modal (Promise-based) ────────────────────────────
function showConfirmDialog({
  title = 'Confirm Action',
  message = 'Are you sure you want to proceed?',
  confirmText = 'Delete',
  cancelText = 'Cancel',
  icon = '🗑️',
  danger = true,
} = {}) {
  return new Promise((resolve) => {
    const modal = document.getElementById('confirm-modal');
    const titleEl = document.getElementById('modal-title');
    const bodyEl = document.getElementById('modal-body');
    const iconEl = document.getElementById('modal-icon');
    const confirmBtn = document.getElementById('modal-confirm-btn');
    const cancelBtn = document.getElementById('modal-cancel-btn');

    if (!modal) {
      resolve(confirm(message));
      return;
    }

    if (titleEl) titleEl.textContent = title;
    if (bodyEl) bodyEl.textContent = message;
    if (iconEl) iconEl.textContent = icon;
    if (confirmBtn) {
      confirmBtn.textContent = confirmText;
      confirmBtn.className = danger ? 'modal-btn btn-danger' : 'modal-btn btn-primary';
    }
    if (cancelBtn) cancelBtn.textContent = cancelText;

    modal.classList.remove('hidden');

    function cleanup(result) {
      modal.classList.add('hidden');
      confirmBtn.onclick = null;
      cancelBtn.onclick = null;
      modal.onclick = null;
      document.removeEventListener('keydown', handleKey);
      resolve(result);
    }

    function handleKey(e) {
      if (e.key === 'Escape') cleanup(false);
      if (e.key === 'Enter') cleanup(true);
    }

    confirmBtn.onclick = () => cleanup(true);
    cancelBtn.onclick = () => cleanup(false);
    modal.onclick = (e) => {
      if (e.target === modal) cleanup(false);
    };
    document.addEventListener('keydown', handleKey);
  });
}

async function deleteMessageById(messageId, btnElement) {
  const confirmed = await showConfirmDialog({
    title: 'Delete Message',
    message: 'Are you sure you want to delete this message? This action cannot be undone.',
    confirmText: 'Delete Message',
    icon: '🗑️',
  });
  if (!confirmed) return;

  const msgEl = btnElement.closest('.message');
  try {
    await api.delete(`/agent/messages/${messageId}`);
    if (msgEl) {
      msgEl.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
      msgEl.style.opacity = '0';
      msgEl.style.transform = 'scale(0.95)';
      setTimeout(() => {
        msgEl.remove();
        const container = document.getElementById('messages-container');
        if (!container.querySelector('.message')) {
          startNewChat();
        }
      }, 250);
    }
    showToast('Message deleted successfully.', 'success');
  } catch (err) {
    showToast(err.message || 'Failed to delete message.', 'error');
  }
}

async function deleteSessionFromSidebar(event, sessionId) {
  event.stopPropagation();
  const confirmed = await showConfirmDialog({
    title: 'Delete Conversation',
    message: 'Are you sure you want to delete this chat conversation and all its messages?',
    confirmText: 'Delete Conversation',
    icon: '🗑️',
  });
  if (!confirmed) return;

  try {
    await api.delete(`/agent/sessions/${sessionId}`);
    if (state.currentSessionId === sessionId) {
      startNewChat();
    }
    await loadSessions();
    showToast('Conversation deleted.', 'success');
  } catch (err) {
    showToast('Failed to delete chat.', 'error');
  }
}

async function deleteCurrentChat() {
  if (!state.currentSessionId) return;
  const confirmed = await showConfirmDialog({
    title: 'Delete Current Chat',
    message: 'Are you sure you want to delete this entire chat conversation? All messages will be permanently removed.',
    confirmText: 'Delete All Messages',
    icon: '🗑️',
  });
  if (!confirmed) return;

  try {
    await api.delete(`/agent/sessions/${state.currentSessionId}`);
    startNewChat();
    await loadSessions();
    showToast('Chat deleted successfully.', 'success');
  } catch (err) {
    showToast('Failed to delete chat.', 'error');
  }
}

function showTyping() {
  const container = document.getElementById('messages-container');
  const div = document.createElement('div');
  div.className = 'typing-indicator';
  div.innerHTML = `
    <div class="message-avatar">📅</div>
    <div class="typing-dots">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
    </div>
  `;
  container.appendChild(div);
  scrollToBottom();
  return div;
}

function showError(msg) {
  appendMessage('assistant', `⚠️ ${msg}`);
}

// ── UI Helpers ─────────────────────────────────────────────────────────────
function scrollToBottom() {
  const c = document.getElementById('messages-container');
  c.scrollTop = c.scrollHeight;
}

function setSendDisabled(disabled) {
  document.getElementById('send-btn').disabled = disabled;
}

function handleKeyDown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  sidebar.classList.toggle('collapsed');
  state.sidebarOpen = !sidebar.classList.contains('collapsed');
}

// ── Markdown Renderer (lightweight) ───────────────────────────────────────
function renderMarkdown(text) {
  return escapeHtml(text)
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`(.*?)`/g, '<code>$1</code>')
    .replace(/^#{1,3}\s(.+)$/gm, '<strong>$1</strong>')
    .replace(/\n/g, '<br/>');
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.appendChild(document.createTextNode(text));
  return div.innerHTML;
}

// ── OAuth Callback Handling ────────────────────────────────────────────────
/**
 * After Google OAuth, the server returns the JWT.
 * We need to handle the redirect back to the app and store the token.
 * The /auth/callback endpoint redirects to /?token=<jwt>
 */
function checkForOAuthToken() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get('token');
  if (token) {
    localStorage.setItem('cal_token', token);
    // Clean URL
    window.history.replaceState({}, document.title, '/');
    location.reload();
  }
}

// ── Init ───────────────────────────────────────────────────────────────────
async function init() {
  checkForOAuthToken();

  const storedToken = localStorage.getItem('cal_token');
  if (!storedToken) {
    showLoginOverlay();
    return;
  }

  state.token = storedToken;

  try {
    const user = await api.get('/auth/me');
    state.user = user;
    renderUserInfo();
    showApp();
    loadSessions();
  } catch (_) {
    clearAuth();
  }
}

// Start app
init();
