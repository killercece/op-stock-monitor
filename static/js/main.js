/* ============================================================
   OP Stock Monitor - Frontend JavaScript
   ============================================================ */

let products = [];
let chartInstance = null;
let searchTimeout = null;
let scanPollInterval = null;

/* ------------------------------------------------------------
   Initialisation
   ------------------------------------------------------------ */

document.addEventListener('DOMContentLoaded', init);

async function init() {
    initTheme();
    await Promise.all([loadSites(), loadSets(), loadStats()]);
    await loadProducts();
    pollScanStatus();
}

/* ------------------------------------------------------------
   Theme
   ------------------------------------------------------------ */

function initTheme() {
    const saved = localStorage.getItem('theme');
    if (saved === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    if (next === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    } else {
        document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem('theme', next);
}

/* ------------------------------------------------------------
   Sidebar mobile
   ------------------------------------------------------------ */

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
}

/* ------------------------------------------------------------
   Chargement des donnees
   ------------------------------------------------------------ */

async function loadProducts() {
    const params = new URLSearchParams();
    const site = document.getElementById('filter-site').value;
    const set = document.getElementById('filter-set').value;
    const stock = document.getElementById('filter-stock').value;
    const sort = document.getElementById('filter-sort').value;
    const search = document.getElementById('filter-search').value;

    if (site) params.set('site', site);
    if (set) params.set('set', set);
    if (stock) params.set('in_stock', stock);
    if (sort) params.set('sort', sort);
    if (search) params.set('search', search);

    try {
        const resp = await fetch('/api/products?' + params.toString());
        products = await resp.json();
        renderProducts(products);
    } catch (e) {
        console.error('Erreur chargement produits:', e);
    }
}

async function loadStats() {
    try {
        const resp = await fetch('/api/stats');
        const stats = await resp.json();
        renderStats(stats);
    } catch (e) {
        console.error('Erreur chargement stats:', e);
    }
}

async function loadSites() {
    try {
        const resp = await fetch('/api/sites');
        const sites = await resp.json();
        const select = document.getElementById('filter-site');
        sites.forEach(function(s) {
            const opt = document.createElement('option');
            opt.value = s.slug;
            opt.textContent = s.name;
            select.appendChild(opt);
        });
    } catch (e) {
        console.error('Erreur chargement sites:', e);
    }
}

async function loadSets() {
    try {
        const resp = await fetch('/api/sets');
        const sets = await resp.json();
        const select = document.getElementById('filter-set');
        sets.forEach(function(s) {
            const opt = document.createElement('option');
            opt.value = s;
            opt.textContent = s;
            select.appendChild(opt);
        });
    } catch (e) {
        console.error('Erreur chargement sets:', e);
    }
}

/* ------------------------------------------------------------
   Rendu
   ------------------------------------------------------------ */

function renderStats(stats) {
    setText('card-total', stats.total_products || 0);
    setText('card-stock', stats.in_stock || 0);
    setText('card-oos', stats.out_of_stock || 0);
    setText('card-avg', stats.avg_price ? stats.avg_price.toFixed(2) + ' \u20ac' : '-');

    setText('stat-total', stats.total_products || 0);
    setText('stat-stock', stats.in_stock || 0);
    setText('stat-sites', stats.total_sites || 0);
    setText('stat-best', stats.best_price ? stats.best_price.toFixed(2) + ' \u20ac' : '-');

    if (stats.last_scan && stats.last_scan.finished_at) {
        var d = new Date(stats.last_scan.finished_at);
        setText('scan-info', 'Dernier scan : ' + formatTime(d));
    }
}

function renderProducts(list) {
    var grid = document.getElementById('product-grid');
    var empty = document.getElementById('empty-state');
    var info = document.getElementById('results-info');

    grid.innerHTML = '';

    if (!list || list.length === 0) {
        grid.appendChild(createEmptyState());
        info.textContent = '';
        return;
    }

    info.textContent = list.length + ' produit' + (list.length > 1 ? 's' : '') + ' trouv\u00e9' + (list.length > 1 ? 's' : '');

    list.forEach(function(p) {
        grid.appendChild(createProductCard(p));
    });
}

function createProductCard(p) {
    var card = document.createElement('div');
    card.className = 'product-card';

    var inStock = p.in_stock === 1;
    var hasPrice = p.price !== null && p.price !== undefined;
    var setCode = p.set_code || '';

    var priceHtml;
    if (hasPrice) {
        var whole = Math.floor(p.price);
        var cents = (p.price % 1).toFixed(2).substring(1);
        priceHtml = '<span class="product-price">' + whole + '<span class="currency">' + cents + ' \u20ac</span></span>';
    } else {
        priceHtml = '<span class="product-price no-price">Prix inconnu</span>';
    }

    var lastSeen = p.checked_at ? formatTime(new Date(p.checked_at)) : '';

    card.innerHTML =
        '<div class="card-top">' +
            '<div class="card-badges">' +
                (setCode ? '<span class="badge badge-set">' + escapeHtml(setCode) + '</span>' : '') +
                '<span class="badge badge-site">' + escapeHtml(p.site_name || '') + '</span>' +
                (inStock
                    ? '<span class="badge badge-stock">\u25CF En stock</span>'
                    : '<span class="badge badge-oos">\u25CF Rupture</span>') +
            '</div>' +
        '</div>' +
        '<div class="card-body">' +
            '<div class="product-name">' + escapeHtml(p.name) + '</div>' +
            '<div class="product-price-row">' +
                priceHtml +
                (lastSeen ? '<span class="product-last-seen">' + lastSeen + '</span>' : '') +
            '</div>' +
        '</div>' +
        '<div class="card-toolbar">' +
            '<a href="' + escapeHtml(p.url) + '" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">Voir le site</a>' +
            '<span class="toolbar-sep"></span>' +
            '<button class="btn btn-ghost btn-sm" onclick="showHistory(' + p.id + ')">Historique</button>' +
        '</div>';

    return card;
}

function createEmptyState() {
    var div = document.createElement('div');
    div.className = 'empty-state';
    div.innerHTML =
        '<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="var(--text-light)" stroke-width="1.5">' +
            '<path d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4M4 7l8 4M4 7v10l8 4m0-10v10"/>' +
        '</svg>' +
        '<h3>Aucun produit</h3>' +
        '<p>Lancez un scan pour commencer la surveillance des sites.</p>' +
        '<button class="btn btn-primary" onclick="triggerScan()">Lancer le premier scan</button>';
    return div;
}

/* ------------------------------------------------------------
   Filtres
   ------------------------------------------------------------ */

function applyFilters() {
    loadProducts();
}

function debounceSearch() {
    if (searchTimeout) clearTimeout(searchTimeout);
    searchTimeout = setTimeout(function() {
        applyFilters();
    }, 400);
}

/* ------------------------------------------------------------
   Scan
   ------------------------------------------------------------ */

async function triggerScan() {
    var btn = document.getElementById('btn-scan');
    btn.disabled = true;
    btn.closest('.toolbar-actions').classList.add('scanning');

    try {
        var resp = await fetch('/api/scan', { method: 'POST' });
        var data = await resp.json();

        if (resp.ok) {
            showToast('Scan lance...', 'info');
            startScanPolling();
        } else {
            showToast(data.error || 'Erreur', 'error');
            btn.disabled = false;
            btn.closest('.toolbar-actions').classList.remove('scanning');
        }
    } catch (e) {
        showToast('Erreur de connexion', 'error');
        btn.disabled = false;
        btn.closest('.toolbar-actions').classList.remove('scanning');
    }
}

function startScanPolling() {
    if (scanPollInterval) clearInterval(scanPollInterval);
    scanPollInterval = setInterval(async function() {
        try {
            var resp = await fetch('/api/scan/status');
            var status = await resp.json();

            if (!status.running) {
                clearInterval(scanPollInterval);
                scanPollInterval = null;
                var btn = document.getElementById('btn-scan');
                btn.disabled = false;
                btn.closest('.toolbar-actions').classList.remove('scanning');
                showToast('Scan termine !', 'success');
                loadProducts();
                loadStats();
                loadSets();
            }
        } catch (e) {
            /* ignorer */
        }
    }, 3000);
}

function pollScanStatus() {
    fetch('/api/scan/status')
        .then(function(r) { return r.json(); })
        .then(function(status) {
            if (status.running) {
                var btn = document.getElementById('btn-scan');
                btn.disabled = true;
                btn.closest('.toolbar-actions').classList.add('scanning');
                startScanPolling();
            }
        })
        .catch(function() {});
}

/* ------------------------------------------------------------
   Historique des prix (modal + chart)
   ------------------------------------------------------------ */

async function showHistory(productId) {
    try {
        var resp = await fetch('/api/products/' + productId + '/history');
        var data = await resp.json();

        if (!resp.ok) {
            showToast(data.error || 'Erreur', 'error');
            return;
        }

        document.getElementById('modal-title').textContent = data.product.name;
        document.getElementById('modal-subtitle').textContent =
            (data.product.set_code || '') + ' \u2014 ' + (data.product.site_name || '');

        renderPriceChart(data.history);
        renderHistoryTable(data.history);

        document.getElementById('modal-overlay').classList.add('active');
    } catch (e) {
        showToast('Erreur chargement historique', 'error');
    }
}

function hideModal() {
    document.getElementById('modal-overlay').classList.remove('active');
    if (chartInstance) {
        chartInstance.destroy();
        chartInstance = null;
    }
}

function renderPriceChart(history) {
    var ctx = document.getElementById('price-chart').getContext('2d');

    if (chartInstance) {
        chartInstance.destroy();
    }

    var labels = [];
    var prices = [];
    var bgColors = [];

    history.forEach(function(h) {
        labels.push(formatDateTime(new Date(h.checked_at)));
        prices.push(h.price);
        bgColors.push(h.in_stock ? 'rgba(16, 185, 129, 0.8)' : 'rgba(239, 68, 68, 0.8)');
    });

    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    var gridColor = isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.06)';
    var textColor = isDark ? '#9ca3af' : '#718096';

    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Prix (\u20ac)',
                data: prices,
                borderColor: '#667eea',
                backgroundColor: 'rgba(102, 126, 234, 0.1)',
                borderWidth: 2,
                pointBackgroundColor: bgColors,
                pointBorderColor: bgColors,
                pointRadius: 5,
                pointHoverRadius: 7,
                fill: true,
                tension: 0.3,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(ctx) {
                            var h = history[ctx.dataIndex];
                            var stock = h.in_stock ? 'En stock' : 'Rupture';
                            var price = ctx.parsed.y !== null ? ctx.parsed.y.toFixed(2) + ' \u20ac' : 'N/A';
                            return price + ' (' + stock + ')';
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: gridColor },
                    ticks: { color: textColor, font: { size: 10 }, maxRotation: 45 }
                },
                y: {
                    grid: { color: gridColor },
                    ticks: {
                        color: textColor,
                        font: { size: 11 },
                        callback: function(v) { return v + ' \u20ac'; }
                    }
                }
            }
        }
    });
}

function renderHistoryTable(history) {
    var wrapper = document.getElementById('history-table-wrapper');
    if (!history || history.length === 0) {
        wrapper.innerHTML = '<p style="padding:16px;color:var(--text-light);font-size:13px;">Aucun historique disponible.</p>';
        return;
    }

    var reversed = history.slice().reverse();
    var rows = '';
    reversed.forEach(function(h) {
        var stockBadge = h.in_stock
            ? '<span class="badge badge-stock">\u25CF En stock</span>'
            : '<span class="badge badge-oos">\u25CF Rupture</span>';
        var price = h.price !== null ? h.price.toFixed(2) + ' \u20ac' : '-';
        rows += '<tr><td>' + formatDateTime(new Date(h.checked_at)) + '</td><td>' + price + '</td><td>' + stockBadge + '</td></tr>';
    });

    wrapper.innerHTML =
        '<table class="history-table">' +
            '<thead><tr><th>Date</th><th>Prix</th><th>Stock</th></tr></thead>' +
            '<tbody>' + rows + '</tbody>' +
        '</table>';
}

/* ------------------------------------------------------------
   Toast
   ------------------------------------------------------------ */

function showToast(message, type) {
    type = type || 'info';
    var container = document.getElementById('toast-container');
    var toast = document.createElement('div');
    toast.className = 'toast ' + type;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(function() {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(12px)';
        toast.style.transition = 'all 0.3s';
        setTimeout(function() { toast.remove(); }, 300);
    }, 3500);
}

/* ------------------------------------------------------------
   Utilitaires
   ------------------------------------------------------------ */

function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
}

function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatTime(date) {
    if (!date || isNaN(date.getTime())) return '';
    var now = new Date();
    var diff = (now - date) / 1000;

    if (diff < 60) return "A l'instant";
    if (diff < 3600) return Math.floor(diff / 60) + ' min';
    if (diff < 86400) return Math.floor(diff / 3600) + ' h';

    return date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
}

function formatDateTime(date) {
    if (!date || isNaN(date.getTime())) return '';
    return date.toLocaleDateString('fr-FR', {
        day: '2-digit', month: '2-digit', year: '2-digit',
        hour: '2-digit', minute: '2-digit'
    });
}
