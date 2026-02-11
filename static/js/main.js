/* ============================================================
   OP Stock Monitor - Frontend JavaScript (v1.2 - Vue groupee)
   ============================================================ */

let groups = [];
let chartInstance = null;
let searchTimeout = null;
let scanPollInterval = null;

/* ------------------------------------------------------------
   Initialisation
   ------------------------------------------------------------ */

document.addEventListener('DOMContentLoaded', init);

async function init() {
    initTheme();
    await Promise.all([loadSets(), loadStats()]);
    await loadProducts();
    pollScanStatus();
}

/* ------------------------------------------------------------
   Theme
   ------------------------------------------------------------ */

function initTheme() {
    var saved = localStorage.getItem('theme');
    if (saved === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    }
}

function toggleTheme() {
    var current = document.documentElement.getAttribute('data-theme');
    var next = current === 'dark' ? 'light' : 'dark';
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
    var params = new URLSearchParams();
    var set = document.getElementById('filter-set').value;
    var stock = document.getElementById('filter-stock').value;
    var search = document.getElementById('filter-search').value;

    if (set) params.set('set', set);
    if (stock) params.set('in_stock', stock);
    if (search) params.set('search', search);

    try {
        var resp = await fetch('/api/products/grouped?' + params.toString());
        groups = await resp.json();
        renderGroups(groups);
    } catch (e) {
        console.error('Erreur chargement produits:', e);
    }
}

async function loadStats() {
    try {
        var resp = await fetch('/api/stats');
        var stats = await resp.json();
        renderStats(stats);
    } catch (e) {
        console.error('Erreur chargement stats:', e);
    }
}

async function loadSets() {
    try {
        var resp = await fetch('/api/sets');
        var sets = await resp.json();
        var select = document.getElementById('filter-set');
        sets.forEach(function(s) {
            var opt = document.createElement('option');
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

function renderGroups(list) {
    var grid = document.getElementById('product-grid');
    var info = document.getElementById('results-info');

    grid.innerHTML = '';

    if (!list || list.length === 0) {
        grid.appendChild(createEmptyState());
        info.textContent = '';
        return;
    }

    var totalShops = 0;
    list.forEach(function(g) { totalShops += g.shops.length; });
    info.textContent = list.length + ' set' + (list.length > 1 ? 's' : '') +
        ' \u2014 ' + totalShops + ' offre' + (totalShops > 1 ? 's' : '');

    list.forEach(function(g) {
        grid.appendChild(createGroupCard(g));
    });
}

function createGroupCard(g) {
    var card = document.createElement('div');
    card.className = 'group-card';

    var hasImage = g.image_url && g.image_url.length > 5;
    var stockClass = g.any_in_stock ? 'badge-stock' : 'badge-oos';
    var stockText = g.any_in_stock ? '\u25CF Disponible' : '\u25CF Rupture';
    var bestPriceHtml = g.best_price
        ? formatPrice(g.best_price)
        : '<span class="no-price">-</span>';

    // Header : image + infos
    var headerHtml =
        '<div class="group-header">' +
            (hasImage
                ? '<div class="group-image"><img src="' + escapeHtml(g.image_url) + '" alt="" loading="lazy"></div>'
                : '<div class="group-image group-image-placeholder"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-light)" stroke-width="1.5"><path d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4M4 7l8 4M4 7v10l8 4m0-10v10"/></svg></div>') +
            '<div class="group-info">' +
                '<span class="badge badge-set">' + escapeHtml(g.set_code) + '</span>' +
                '<h3 class="group-name">' + escapeHtml(g.name) + '</h3>' +
                '<div class="group-meta">' +
                    '<span class="badge ' + stockClass + '">' + stockText + '</span>' +
                    '<span class="group-best-price">Meilleur prix : ' + bestPriceHtml + '</span>' +
                '</div>' +
            '</div>' +
        '</div>';

    // Tableau des boutiques
    var shopRows = '';
    g.shops.forEach(function(s) {
        var priceText = s.price ? s.price.toFixed(2) + ' \u20ac' : '-';
        var stockBadge = s.in_stock
            ? '<span class="badge badge-stock badge-sm">\u25CF En stock</span>'
            : '<span class="badge badge-oos badge-sm">\u25CF Rupture</span>';
        var isBest = s.price && g.best_price && s.price === g.best_price && s.in_stock;

        shopRows +=
            '<tr class="' + (s.in_stock ? '' : 'shop-oos') + '">' +
                '<td class="shop-name">' + escapeHtml(s.site_name) + '</td>' +
                '<td class="shop-price' + (isBest ? ' best-price' : '') + '">' + priceText + '</td>' +
                '<td>' + stockBadge + '</td>' +
                '<td class="shop-actions">' +
                    '<a href="' + escapeHtml(s.url) + '" target="_blank" rel="noopener" class="btn btn-ghost btn-xs">Voir</a>' +
                    '<button class="btn btn-ghost btn-xs" onclick="showHistory(' + s.product_id + ')">Historique</button>' +
                '</td>' +
            '</tr>';
    });

    var tableHtml =
        '<div class="shop-table-wrapper">' +
            '<table class="shop-table">' +
                '<thead><tr>' +
                    '<th>Boutique</th>' +
                    '<th>Prix</th>' +
                    '<th>Stock</th>' +
                    '<th></th>' +
                '</tr></thead>' +
                '<tbody>' + shopRows + '</tbody>' +
            '</table>' +
        '</div>';

    card.innerHTML = headerHtml + tableHtml;
    return card;
}

function formatPrice(price) {
    var whole = Math.floor(price);
    var cents = (price % 1).toFixed(2).substring(1);
    return '<span class="price-value">' + whole + '<span class="price-cents">' + cents + ' \u20ac</span></span>';
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
