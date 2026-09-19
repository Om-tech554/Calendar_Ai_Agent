/**
 * Admin Dashboard Client-side JavaScript.
 * Handles authentication guard, live metrics fetching, search filters, and auto-refresh.
 */

// ── State ────────────────────────────────────────────────────────────────────
const state = {
  token: localStorage.getItem('cal_token') || localStorage.getItem('auth_token') || null,
  user: null,
  usersList: [],
  autoRefreshInterval: null,
  countdownInterval: null,
  resetInSeconds: 0,
};

// ── API Helper ───────────────────────────────────────────────────────────────
async function apiFetch(endpoint, options = {}) {
  if (!state.token) {
    throw new Error('AUTH_REQUIRED');
  }

  const res = await fetch(endpoint, {
    ...options,
    headers: {
      'Authorization': `Bearer ${state.token}`,
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });

  if (res.status === 401) {
    throw new Error('AUTH_REQUIRED');
  }
  if (res.status === 403) {
    throw new Error('ADMIN_REQUIRED');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail?.message || `Error ${res.status}`);
  }

  return res.json();
}

// ── Auth Verification ────────────────────────────────────────────────────────
async function verifyAdminAuth() {
  if (!state.token) {
    showAccessDenied('You are not logged in. Please sign in to your admin account first.');
    return false;
  }

  try {
    const me = await apiFetch('/auth/me');
    state.user = me;

    if (!me.is_admin) {
      showAccessDenied(`Access Denied: The account ${me.email} is not listed in ADMIN_EMAILS.`);
      return false;
    }

    // Populate admin profile pill
    document.getElementById('admin-name').textContent = me.name || me.email;
    const avatar = document.getElementById('admin-avatar');
    if (me.picture_url) {
      avatar.src = me.picture_url;
    } else {
      avatar.style.display = 'none';
    }

    return true;

  } catch (err) {
    if (err.message === 'ADMIN_REQUIRED') {
      showAccessDenied('Admin privileges required to view this dashboard.');
    } else {
      showAccessDenied('Session expired or invalid. Please sign in again.');
    }
    return false;
  }
}

function showAccessDenied(reason) {
  document.getElementById('denied-reason').textContent = reason;
  document.getElementById('denied-screen').classList.remove('hidden');
}

// ── Load All Dashboard Data ──────────────────────────────────────────────────
async function loadDashboard() {
  const refreshIcon = document.querySelector('.refresh-icon');
  if (refreshIcon) refreshIcon.style.animation = 'spin 0.8s linear infinite';
  document.getElementById('last-updated-text').textContent = 'Updating...';

  try {
    const [overview, quotas, users, activity] = await Promise.all([
      apiFetch('/api/admin/overview'),
      apiFetch('/api/admin/quotas'),
      apiFetch('/api/admin/users'),
      apiFetch('/api/admin/activity'),
    ]);

    renderOverview(overview);
    renderQuotas(quotas);
    renderUsers(users);
    renderActivity(activity);

    const now = new Date();
    document.getElementById('last-updated-text').textContent = 
      `Updated ${now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;

  } catch (err) {
    console.error('Failed to load dashboard:', err);
    document.getElementById('last-updated-text').textContent = 'Update failed';
  } finally {
    if (refreshIcon) refreshIcon.style.animation = 'none';
  }
}

// ── Render Functions ─────────────────────────────────────────────────────────

function renderOverview(data) {
  // KPI Cards
  document.getElementById('kpi-total-users').textContent = data.total_users;
  document.getElementById('kpi-active-today').textContent = `${data.active_users_today} active today`;
  document.getElementById('kpi-active-7d').textContent = `${data.active_users_7d} this week`;
  document.getElementById('badge-total-users').textContent = data.total_users;

  document.getElementById('kpi-total-messages').textContent = data.total_messages;
  document.getElementById('kpi-total-sessions').textContent = `${data.total_sessions} total sessions started`;

  // Gemini Free Tier Progress
  document.getElementById('kpi-gemini-used').textContent = data.gemini_requests_today;
  document.getElementById('kpi-gemini-limit').textContent = `/ ${data.gemini_daily_limit} daily`;
  
  const progressBar = document.getElementById('gemini-progress-bar');
  const pct = Math.min(100, data.gemini_used_percent);
  progressBar.style.width = `${pct}%`;
  
  if (pct >= 85) {
    progressBar.style.background = 'linear-gradient(90deg, #f59e0b, #ef4444)';
  } else if (pct >= 60) {
    progressBar.style.background = 'linear-gradient(90deg, #10b981, #f59e0b)';
  } else {
    progressBar.style.background = 'linear-gradient(90deg, #06b6d4, #10b981)';
  }

  document.getElementById('gemini-remaining-text').textContent = `${data.gemini_remaining} requests left today (${pct}%)`;

  // Calendar
  document.getElementById('kpi-calendar-queries').textContent = data.calendar_queries_today;
  document.getElementById('env-badge').textContent = data.app_env.toUpperCase();

  // Reset Countdown
  state.resetInSeconds = data.reset_in_seconds;
  startResetCountdown();

  // Database Breakdown
  const dbGrid = document.getElementById('db-counts-grid');
  dbGrid.innerHTML = '';
  for (const [colName, count] of Object.entries(data.db_collections)) {
    const box = document.createElement('div');
    box.className = 'db-count-box';
    box.innerHTML = `
      <div class="db-count-num">${count}</div>
      <div class="db-count-name">${colName}</div>
    `;
    dbGrid.appendChild(box);
  }
}

function startResetCountdown() {
  if (state.countdownInterval) clearInterval(state.countdownInterval);

  function updateDisplay() {
    if (state.resetInSeconds <= 0) {
      document.getElementById('reset-countdown').textContent = 'Resetting now...';
      return;
    }
    const hours = Math.floor(state.resetInSeconds / 3600);
    const mins = Math.floor((state.resetInSeconds % 3600) / 60);
    const secs = state.resetInSeconds % 60;
    const formatted = `${hours}h ${mins}m ${secs}s`;
    document.getElementById('reset-countdown').textContent = `Quota resets in ${formatted}`;
    state.resetInSeconds--;
  }

  updateDisplay();
  state.countdownInterval = setInterval(updateDisplay, 1000);
}

function renderQuotas(quotas) {
  const container = document.getElementById('quota-cards-grid');
  container.innerHTML = '';

  quotas.forEach(q => {
    const card = document.createElement('div');
    card.className = 'quota-item-card';

    const statusClass = q.status;
    const statusText = q.status === 'healthy' ? 'Healthy (Free Tier)' : q.status.toUpperCase();

    card.innerHTML = `
      <div class="quota-top">
        <div>
          <div class="quota-service-name">${escapeHtml(q.service)}</div>
          <span class="quota-tier-tag">${escapeHtml(q.tier)}</span>
        </div>
        <span class="status-badge ${statusClass}">${statusText}</span>
      </div>

      <div class="quota-stats-row">
        <div class="quota-metric-col">
          <span class="quota-stat-label">Used Today</span>
          <span class="quota-stat-val">${q.used_today.toLocaleString()}</span>
        </div>
        <div class="quota-metric-col">
          <span class="quota-stat-label">Daily Limit</span>
          <span class="quota-stat-val">${q.limit.toLocaleString()}</span>
        </div>
        <div class="quota-metric-col">
          <span class="quota-stat-label">Remaining</span>
          <span class="quota-stat-val">${q.remaining_today.toLocaleString()}</span>
        </div>
      </div>

      <div class="progress-bar-container">
        <div class="progress-bar" style="width: ${Math.min(100, q.used_percent)}%;"></div>
      </div>

      <div class="kpi-subtext space-between">
        <span>${q.used_percent}% utilized today</span>
        <span class="text-dim">Resets: ${q.reset_time_utc}</span>
      </div>
    `;

    container.appendChild(card);
  });
}

function renderUsers(users) {
  state.usersList = users;
  filterAndRenderUsers();
}

function filterAndRenderUsers() {
  const query = (document.getElementById('user-search-input')?.value || '').toLowerCase().trim();
  const tbody = document.getElementById('users-table-body');
  if (!tbody) return;

  const filtered = state.usersList.filter(u => 
    u.name.toLowerCase().includes(query) || u.email.toLowerCase().includes(query)
  );

  document.getElementById('user-count-display').textContent = filtered.length;

  if (!filtered.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="9" class="loading-td">No users found matching "${escapeHtml(query)}"</td>
      </tr>
    `;
    return;
  }

  const currentUserId = state.user ? state.user.id : '';

  tbody.innerHTML = filtered.map(u => {
    const joined = new Date(u.created_at).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
    const lastActive = new Date(u.last_login_at).toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    const avatar = u.picture_url || 'https://www.gravatar.com/avatar/?d=mp';

    const calBadge = u.calendar_connected
      ? `<span class="badge-connected">✓ Connected</span>`
      : `<span class="badge-disconnected">Not Connected</span>`;

    let roleBadge = `<span class="badge-role badge-role-user">👤 User</span>`;
    if (u.is_superadmin) {
      roleBadge = `<span class="badge-role badge-role-super">👑 Superadmin</span>`;
    } else if (u.is_admin) {
      roleBadge = `<span class="badge-role badge-role-admin">🛡️ Admin</span>`;
    }

    let actionCell = `<span class="text-dim">—</span>`;
    if (u.is_superadmin) {
      actionCell = `<span class="text-dim" title="Configured in server environment">Superadmin</span>`;
    } else if (u.id === currentUserId) {
      actionCell = `<span class="badge-current-user">You</span>`;
    } else if (u.is_admin) {
      actionCell = `<button class="btn-role-action btn-demote" onclick="changeUserRole('${u.id}', 'user', '${escapeHtml(u.email)}')">Revoke Admin</button>`;
    } else {
      actionCell = `<button class="btn-role-action btn-promote" onclick="changeUserRole('${u.id}', 'admin', '${escapeHtml(u.email)}')">Grant Admin</button>`;
    }

    return `
      <tr>
        <td>
          <div class="user-cell">
            <img src="${avatar}" alt="" onerror="this.src='https://www.gravatar.com/avatar/?d=mp'">
            <strong>${escapeHtml(u.name)}</strong>
          </div>
        </td>
        <td><code>${escapeHtml(u.email)}</code></td>
        <td>${roleBadge}</td>
        <td>${joined}</td>
        <td>${lastActive}</td>
        <td><strong>${u.session_count}</strong></td>
        <td>${u.message_count}</td>
        <td>${calBadge}</td>
        <td>${actionCell}</td>
      </tr>
    `;
  }).join('');
}

function renderActivity(activities) {
  const container = document.getElementById('activity-timeline');
  if (!container) return;

  if (!activities.length) {
    container.innerHTML = '<div class="loading-td">No recent activity found.</div>';
    return;
  }

  container.innerHTML = activities.map(item => {
    const timeAgo = formatTimeAgo(new Date(item.timestamp));
    const icon = item.type === 'user_message' ? '👤' : '🤖';

    return `
      <div class="timeline-item">
        <div class="timeline-icon">${icon}</div>
        <div class="timeline-body">
          <div class="timeline-title-row">
            <span class="timeline-title">${escapeHtml(item.title)}</span>
            <span class="timeline-time">${timeAgo}</span>
          </div>
          <div class="timeline-detail">${escapeHtml(item.detail)}</div>
        </div>
      </div>
    `;
  }).join('');
}

// ── Tab Switching ────────────────────────────────────────────────────────────
function setupTabs() {
  const buttons = document.querySelectorAll('.nav-item');
  const title = document.getElementById('page-title');

  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetTab = btn.dataset.tab;
      if (!targetTab) return;

      // Update active nav button
      buttons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      // Update tab pane
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      const activePane = document.getElementById(targetTab);
      if (activePane) activePane.classList.add('active');

      // Update Header Title
      if (targetTab === 'tab-overview') title.textContent = 'Operational Overview & Quotas';
      if (targetTab === 'tab-users') title.textContent = 'Registered Users Directory';
      if (targetTab === 'tab-activity') title.textContent = 'System Activity Timeline';
    });
  });
}

// ── Search & Refresh Listeners ───────────────────────────────────────────────
function setupEventListeners() {
  const searchInput = document.getElementById('user-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', filterAndRenderUsers);
  }

  const refreshBtn = document.getElementById('btn-refresh');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', loadDashboard);
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/[&<>"']/g, m => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  })[m]);
}

function formatTimeAgo(date) {
  const now = new Date();
  const diffSecs = Math.floor((now - date) / 1000);
  if (diffSecs < 60) return 'just now';
  const mins = Math.floor(diffSecs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
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
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  icon = '🛡️',
  danger = false,
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

// ── Role Management ─────────────────────────────────────────────────────────
async function changeUserRole(userId, newRole, email) {
  const isPromote = newRole === 'admin';
  const actionText = isPromote
    ? `grant Administrator privileges to ${email}`
    : `revoke Administrator privileges from ${email}`;

  const confirmed = await showConfirmDialog({
    title: isPromote ? 'Grant Admin Privileges' : 'Revoke Admin Privileges',
    message: `Are you sure you want to ${actionText}? ${isPromote ? 'This user will gain access to the Admin Dashboard and all system metrics.' : 'This user will be demoted to standard user.'}`,
    confirmText: isPromote ? 'Grant Admin' : 'Revoke Admin',
    icon: isPromote ? '👑' : '⚠️',
    danger: !isPromote,
  });
  if (!confirmed) return;

  try {
    const updated = await apiFetch(`/api/admin/users/${userId}/role`, {
      method: 'POST',
      body: JSON.stringify({ role: newRole }),
    });

    const idx = state.usersList.findIndex(u => u.id === userId);
    if (idx !== -1) {
      state.usersList[idx] = updated;
      filterAndRenderUsers();
    }
    showToast(`User ${email} is now ${isPromote ? 'an Administrator' : 'a standard User'}.`, 'success');
  } catch (err) {
    showToast(`Failed to update user role: ${err.message}`, 'error');
  }
}

// ── Initialization ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  setupTabs();
  setupEventListeners();

  const isAuthed = await verifyAdminAuth();
  if (isAuthed) {
    await loadDashboard();
    // Auto-refresh every 30 seconds
    state.autoRefreshInterval = setInterval(loadDashboard, 30000);
  }
});
