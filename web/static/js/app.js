/**
 * LinkedIn Hunter CRM — Frontend Logic
 * Fetch API + client-side filtering + pipeline actions
 */

// ─── State ───────────────────────────────────────────────────────────────────

let currentFilter = 'all';
let searchQuery = '';
let jobPollingInterval = null;

// ─── API ─────────────────────────────────────────────────────────────────────

async function fetchLeads() {
    const params = new URLSearchParams();
    if (currentFilter !== 'all') params.set('status', currentFilter);
    if (searchQuery) params.set('search', searchQuery);
    const res = await fetch(`/api/leads?${params}`);
    return res.json();
}

async function fetchStats() {
    const res = await fetch('/api/stats');
    return res.json();
}

async function runAction(action) {
    const res = await fetch(`/api/actions/${action}`, { method: 'POST' });
    return res.json();
}

async function fetchJobStatus() {
    const res = await fetch('/api/actions/status');
    return res.json();
}

// ─── Rendering ───────────────────────────────────────────────────────────────

function getStatusBadgeClass(status) {
    const map = {
        'Prospect': 'badge-prospect',
        'Qualificado': 'badge-qualified',
        'Desqualificado': 'badge-disqualified',
        'Conexão Enviada': 'badge-sent',
        'Conectado': 'badge-connected',
        'DM1 Enviada': 'badge-dm1',
        'Respondeu': 'badge-replied',
        'Convertido': 'badge-converted',
    };
    return map[status] || 'badge-prospect';
}

function getScoreClass(score) {
    if (score >= 60) return 'high';
    if (score >= 40) return 'medium';
    return 'low';
}

function renderStats(stats) {
    document.getElementById('stat-total').textContent = stats.total || 0;
    document.getElementById('stat-qualified').textContent = stats.funnel?.qualificados || 0;
    document.getElementById('stat-sent').textContent = stats.funnel?.conexoes_enviadas || 0;
    document.getElementById('stat-converted').textContent = stats.funnel?.convertidos || 0;

    // Daily activity
    document.getElementById('stat-daily-connections').textContent = stats.daily?.conexoes_enviadas || 0;
    document.getElementById('stat-daily-visits').textContent = stats.daily?.perfis_visitados || 0;
    document.getElementById('stat-daily-messages').textContent = stats.daily?.mensagens_enviadas || 0;
}

function renderLeads(leads) {
    const tbody = document.getElementById('leads-tbody');
    const emptyState = document.getElementById('empty-state');

    if (!leads || leads.length === 0) {
        tbody.innerHTML = '';
        emptyState.style.display = 'block';
        return;
    }

    emptyState.style.display = 'none';

    tbody.innerHTML = leads.map(lead => {
        const score = lead.score_icp || 0;
        const scoreClass = getScoreClass(score);
        const badgeClass = getStatusBadgeClass(lead.status);
        const nome = lead.nome || '—';
        const cargo = lead.cargo || '';
        const empresa = lead.empresa || '';
        const url = lead.url_perfil || '#';
        const dataDesc = lead.data_descoberta
            ? new Date(lead.data_descoberta).toLocaleDateString('pt-BR')
            : '—';

        return `
      <tr>
        <td>
          <div class="lead-name">${escapeHtml(nome)}</div>
          <div class="lead-company">${escapeHtml(empresa)}</div>
        </td>
        <td>${escapeHtml(cargo)}</td>
        <td>
          <div class="score-container">
            <div class="score-bar">
              <div class="score-bar-fill ${scoreClass}" style="width: ${score}%"></div>
            </div>
            <span class="score-value">${score}</span>
          </div>
        </td>
        <td><span class="badge ${badgeClass}">${escapeHtml(lead.status || 'Prospect')}</span></td>
        <td>${dataDesc}</td>
        <td><a href="${escapeHtml(url)}" target="_blank" class="lead-link">Perfil ↗</a></td>
      </tr>
    `;
    }).join('');
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ─── Toast Notifications ─────────────────────────────────────────────────────

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

// ─── Filters ─────────────────────────────────────────────────────────────────

function setFilter(status) {
    currentFilter = status;
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.status === status);
    });
    loadLeads();
}

function handleSearch(e) {
    searchQuery = e.target.value;
    clearTimeout(window._searchTimeout);
    window._searchTimeout = setTimeout(loadLeads, 300);
}

// ─── Pipeline Actions ────────────────────────────────────────────────────────

async function triggerAction(action) {
    const labels = {
        discover: 'Discovery', validate: 'Validação',
        outreach: 'Outreach', monitor: 'Monitor',
    };

    try {
        const res = await runAction(action);
        if (res.error) {
            showToast(res.error, 'error');
            return;
        }
        showToast(`${labels[action]} iniciado...`, 'info');
        startJobPolling();
    } catch (e) {
        showToast('Erro ao iniciar ação', 'error');
    }
}

function startJobPolling() {
    if (jobPollingInterval) return;
    updateJobBanner();
    jobPollingInterval = setInterval(updateJobBanner, 2000);
}

async function updateJobBanner() {
    try {
        const status = await fetchJobStatus();
        const banner = document.getElementById('job-banner');
        const bannerText = document.getElementById('job-banner-text');

        if (status.running) {
            banner.classList.add('visible');
            bannerText.textContent = status.message;
            setActionButtonsRunning(true);
        } else {
            banner.classList.remove('visible');
            setActionButtonsRunning(false);

            if (jobPollingInterval) {
                clearInterval(jobPollingInterval);
                jobPollingInterval = null;
            }

            if (status.message && status.message.startsWith('✓')) {
                showToast(status.message, 'success');
            } else if (status.message && status.message.startsWith('✗')) {
                showToast(status.message, 'error');
            }

            // Refresh data
            loadAll();
        }
    } catch (e) {
        // Ignore polling errors
    }
}

function setActionButtonsRunning(running) {
    document.querySelectorAll('.action-btn').forEach(btn => {
        btn.classList.toggle('running', running);
    });
}

// ─── Loading ─────────────────────────────────────────────────────────────────

async function loadLeads() {
    try {
        const leads = await fetchLeads();
        renderLeads(leads);
    } catch (e) {
        showToast('Erro ao carregar leads', 'error');
    }
}

async function loadStats() {
    try {
        const stats = await fetchStats();
        renderStats(stats);
    } catch (e) {
        // Silently fail
    }
}

async function loadAll() {
    await Promise.all([loadLeads(), loadStats()]);
}

// ─── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    loadAll();

    // Check if there's an existing job running
    fetchJobStatus().then(status => {
        if (status.running) startJobPolling();
    });

    // Refresh every 30s
    setInterval(loadAll, 30000);
});
