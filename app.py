"""
Application Flask - OP Stock Monitor
Surveillance de stock et prix de displays One Piece TCG
sur les principaux sites e-commerce francais.
"""

__version__ = '1.0.0'

from flask import Flask, render_template, jsonify, request, g
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
import requests as http_requests
import sqlite3
import logging
import os
import json
import time
import re
import threading
import atexit
from pathlib import Path
from datetime import datetime

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialiser Flask
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-key-change-me-in-production')

# Configuration
DB_PATH = Path(os.getenv('DATABASE_PATH', 'data/app.db'))
SCAN_INTERVAL_MINUTES = int(os.getenv('SCAN_INTERVAL', '15'))
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '30'))

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)

# Etat du dernier scan (partage entre threads)
last_scan_info = {
    'started_at': None,
    'finished_at': None,
    'results': {},
    'running': False,
}
scan_lock = threading.Lock()


# ============================================================
# BASE DE DONNEES
# ============================================================

def get_db():
    """Connexion a la base de donnees avec reutilisation par requete."""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    """Ferme la connexion a la fin de la requete."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def get_standalone_db():
    """Connexion standalone hors contexte Flask (scheduler)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# UTILITAIRES SCRAPING
# ============================================================

def fetch_page(url):
    """Recupere le contenu HTML d'une page."""
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.5',
    }
    try:
        response = http_requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.text
    except http_requests.RequestException as e:
        logger.error(f"Erreur requete {url}: {e}")
        return None


def detect_set_code(name):
    """Detecte le code du set One Piece (OP01, OP02...) dans le nom du produit."""
    match = re.search(r'(?:OP|op)[-\s]?(\d{2})', name)
    if match:
        return f"OP{match.group(1)}"
    set_names = {
        'romance dawn': 'OP01',
        'paramount war': 'OP02',
        'pillars of strength': 'OP03',
        'kingdoms of intrigue': 'OP04',
        'awakening of the new era': 'OP05',
        'wings of the captain': 'OP06',
        '500 years in the future': 'OP07',
        'two legends': 'OP08',
        'the four emperors': 'OP09',
        'royal blood': 'OP10',
    }
    name_lower = name.lower()
    for set_name, code in set_names.items():
        if set_name in name_lower:
            return code
    return None


def parse_price(price_text):
    """Parse un prix textuel en float."""
    if not price_text:
        return None
    cleaned = price_text.strip().replace('\u20ac', '').replace('EUR', '').strip()
    cleaned = cleaned.replace('\xa0', '').replace(' ', '')
    cleaned = cleaned.replace(',', '.')
    match = re.search(r'(\d+\.?\d*)', cleaned)
    if match:
        return float(match.group(1))
    return None


# ============================================================
# SCRAPERS PAR SITE
# ============================================================

def scrape_cardmarket(url):
    """Scraper pour Cardmarket - Booster Boxes One Piece."""
    products = []
    html = fetch_page(url)
    if not html:
        return products

    soup = BeautifulSoup(html, 'html.parser')

    for item in soup.select('.table-body .row, .col-12.col-md-8, .product-card'):
        try:
            name_el = item.select_one('a[href*="/Products/"], a.name')
            price_el = item.select_one('.price-container span, .col-price span, .price')
            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            if not any(kw in name.lower() for kw in ['one piece', 'op-', 'op0']):
                continue

            price = parse_price(price_el.get_text() if price_el else '')
            link = name_el.get('href', '')
            if link and not link.startswith('http'):
                link = f"https://www.cardmarket.com{link}"

            img_el = item.select_one('img')
            image = img_el.get('src', '') if img_el else ''
            in_stock = price is not None and price > 0

            products.append({
                'name': name, 'price': price, 'in_stock': in_stock,
                'url': link, 'image_url': image, 'set_code': detect_set_code(name),
            })
        except Exception as e:
            logger.warning(f"Erreur parsing Cardmarket: {e}")
    return products


def scrape_pokecardex(url):
    """Scraper pour Pokecardex."""
    products = []
    html = fetch_page(url)
    if not html:
        return products

    soup = BeautifulSoup(html, 'html.parser')

    for item in soup.select('.product-item, .item.product, .product-miniature, li.item'):
        try:
            name_el = item.select_one('.product-item-name a, .product-name a, h2 a, .name a')
            price_el = item.select_one('.price, .product-price, span[data-price-amount]')
            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            if not any(kw in name.lower() for kw in ['one piece', 'op-', 'op0']):
                continue

            price = parse_price(price_el.get_text() if price_el else '')
            link = name_el.get('href', '')

            img_el = item.select_one('img.product-image-photo, img')
            image = img_el.get('src', '') if img_el else ''

            stock_el = item.select_one('.stock, .availability')
            in_stock = True
            if stock_el:
                stock_text = stock_el.get_text(strip=True).lower()
                in_stock = 'rupture' not in stock_text and 'indisponible' not in stock_text

            products.append({
                'name': name, 'price': price, 'in_stock': in_stock,
                'url': link, 'image_url': image, 'set_code': detect_set_code(name),
            })
        except Exception as e:
            logger.warning(f"Erreur parsing Pokecardex: {e}")
    return products


def scrape_ultrajeux(url):
    """Scraper pour UltraJeux."""
    products = []
    html = fetch_page(url)
    if not html:
        return products

    soup = BeautifulSoup(html, 'html.parser')

    for item in soup.select('.product-block, .product-item, .recherche_produit, .product_list_item'):
        try:
            name_el = item.select_one('a.product-name, h3 a, .name a, a[title]')
            price_el = item.select_one('.price, .product-price, .prix')
            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            if not any(kw in name.lower() for kw in ['one piece', 'op-', 'op0', 'display']):
                continue

            price = parse_price(price_el.get_text() if price_el else '')
            link = name_el.get('href', '')
            if link and not link.startswith('http'):
                link = f"https://www.ultrajeux.com{link}"

            img_el = item.select_one('img')
            image = img_el.get('data-src', img_el.get('src', '')) if img_el else ''

            stock_el = item.select_one('.availability, .stock')
            in_stock = True
            if stock_el:
                stock_text = stock_el.get_text(strip=True).lower()
                in_stock = 'rupture' not in stock_text and 'indisponible' not in stock_text

            products.append({
                'name': name, 'price': price, 'in_stock': in_stock,
                'url': link, 'image_url': image, 'set_code': detect_set_code(name),
            })
        except Exception as e:
            logger.warning(f"Erreur parsing UltraJeux: {e}")
    return products


def scrape_prestashop(url, base_url):
    """Scraper generique pour sites PrestaShop (Philibert, LudiCorner, Dernier Bastion)."""
    products = []
    html = fetch_page(url)
    if not html:
        return products

    soup = BeautifulSoup(html, 'html.parser')

    for item in soup.select('.product-miniature, .product-container, .product_list_item, .product-item'):
        try:
            name_el = item.select_one('.product-title a, h3 a, .name a, a.product-name')
            price_el = item.select_one('.price, .product-price, span[itemprop="price"]')
            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            if not any(kw in name.lower() for kw in ['one piece', 'op-', 'op0', 'display']):
                continue

            price = parse_price(price_el.get_text() if price_el else '')
            link = name_el.get('href', '')
            if link and not link.startswith('http'):
                link = f"{base_url}{link}"

            img_el = item.select_one('img')
            image = img_el.get('data-src', img_el.get('src', '')) if img_el else ''

            out_of_stock_el = item.select_one('.out-of-stock, .unavailable, .rupture')
            add_to_cart = item.select_one('.add-to-cart, [data-button-action="add-to-cart"]')
            stock_el = item.select_one('.availability, .stock, .product-availability')

            if out_of_stock_el:
                in_stock = False
            elif add_to_cart:
                in_stock = not add_to_cart.get('disabled')
            elif stock_el:
                stock_text = stock_el.get_text(strip=True).lower()
                in_stock = 'rupture' not in stock_text and 'indisponible' not in stock_text
            else:
                in_stock = price is not None

            products.append({
                'name': name, 'price': price, 'in_stock': in_stock,
                'url': link, 'image_url': image, 'set_code': detect_set_code(name),
            })
        except Exception as e:
            logger.warning(f"Erreur parsing PrestaShop ({base_url}): {e}")
    return products


# Registre des scrapers : slug -> fonction
SCRAPER_REGISTRY = {
    'cardmarket': scrape_cardmarket,
    'pokecardex': scrape_pokecardex,
    'ultrajeux': scrape_ultrajeux,
    'philibert': lambda url: scrape_prestashop(url, 'https://www.philibert.net'),
    'ludicorner': lambda url: scrape_prestashop(url, 'https://www.ludicorner.com'),
    'dernier-bastion': lambda url: scrape_prestashop(url, 'https://www.dernierbastion.fr'),
}


# ============================================================
# SCANNER
# ============================================================

def save_product(conn, site_id, product_data):
    """Sauvegarde ou met a jour un produit et son historique de prix."""
    url = product_data.get('url', '')
    if not url:
        return

    existing = conn.execute("SELECT id FROM products WHERE url = ?", (url,)).fetchone()

    if existing:
        product_id = existing['id']
        conn.execute(
            """UPDATE products SET name = ?, set_code = COALESCE(?, set_code),
               image_url = COALESCE(NULLIF(?, ''), image_url), last_seen = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (product_data['name'], product_data.get('set_code'),
             product_data.get('image_url', ''), product_id)
        )
    else:
        cursor = conn.execute(
            """INSERT INTO products (site_id, name, set_code, url, image_url)
               VALUES (?, ?, ?, ?, ?)""",
            (site_id, product_data['name'], product_data.get('set_code'),
             url, product_data.get('image_url', ''))
        )
        product_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO price_history (product_id, price, in_stock) VALUES (?, ?, ?)",
        (product_id, product_data.get('price'), 1 if product_data.get('in_stock') else 0)
    )
    conn.commit()


def run_scan():
    """Lance un scan complet de tous les sites actives."""
    global last_scan_info

    with scan_lock:
        if last_scan_info['running']:
            logger.warning("Scan deja en cours, abandon")
            return
        last_scan_info['running'] = True

    last_scan_info['started_at'] = datetime.now().isoformat()
    last_scan_info['results'] = {}

    logger.info("=== Debut du scan ===")
    conn = get_standalone_db()

    try:
        sites = conn.execute("SELECT * FROM sites WHERE enabled = 1").fetchall()

        for site in sites:
            site_slug = site['slug']
            scraper_fn = SCRAPER_REGISTRY.get(site_slug)

            if not scraper_fn:
                logger.warning(f"Pas de scraper pour {site_slug}")
                last_scan_info['results'][site_slug] = {'status': 'no_scraper', 'count': 0}
                continue

            logger.info(f"Scan de {site['name']}...")
            site_products = []
            search_urls = json.loads(site['search_urls']) if site['search_urls'] else []

            for url in search_urls:
                try:
                    found = scraper_fn(url)
                    site_products.extend(found)
                    logger.info(f"  {url} -> {len(found)} produits")
                    time.sleep(2)
                except Exception as e:
                    logger.error(f"  Erreur sur {url}: {e}")

            saved = 0
            for product in site_products:
                try:
                    save_product(conn, site['id'], product)
                    saved += 1
                except Exception as e:
                    logger.error(f"  Erreur sauvegarde: {e}")

            last_scan_info['results'][site_slug] = {
                'status': 'ok', 'count': saved, 'total_found': len(site_products),
            }
            logger.info(f"  {site['name']}: {saved}/{len(site_products)} sauvegardes")

        conn.execute(
            "INSERT INTO scan_log (started_at, finished_at, results) VALUES (?, ?, ?)",
            (last_scan_info['started_at'], datetime.now().isoformat(),
             json.dumps(last_scan_info['results']))
        )
        conn.commit()

    except Exception as e:
        logger.error(f"Erreur scan: {e}")
    finally:
        conn.close()
        with scan_lock:
            last_scan_info['running'] = False
        last_scan_info['finished_at'] = datetime.now().isoformat()
        logger.info("=== Fin du scan ===")


# ============================================================
# SCHEDULER
# ============================================================

scheduler = BackgroundScheduler(daemon=True)


def init_scheduler():
    """Initialise le scheduler pour les scans periodiques."""
    if not DB_PATH.exists():
        logger.warning("Base de donnees absente, scheduler non demarre")
        return
    if scheduler.running:
        return

    scheduler.add_job(
        run_scan, 'interval',
        minutes=SCAN_INTERVAL_MINUTES,
        id='periodic_scan',
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))
    logger.info(f"Scheduler demarre - scan toutes les {SCAN_INTERVAL_MINUTES} min")


# ============================================================
# ROUTES API
# ============================================================

@app.route('/api/health')
def health():
    """Health check endpoint pour PyDeploy."""
    return jsonify({"status": "ok", "version": __version__}), 200


@app.route('/api/products')
def api_products():
    """Liste des produits avec filtres optionnels."""
    try:
        db = get_db()
        site_slug = request.args.get('site', '')
        set_code = request.args.get('set', '')
        in_stock = request.args.get('in_stock', '')
        sort = request.args.get('sort', 'price_asc')
        search = request.args.get('search', '')

        query = """
            SELECT p.id, p.name, p.set_code, p.url, p.image_url,
                   p.first_seen, p.last_seen,
                   s.name as site_name, s.slug as site_slug, s.url as site_url,
                   ph.price, ph.in_stock, ph.checked_at
            FROM products p
            JOIN sites s ON p.site_id = s.id
            LEFT JOIN price_history ph ON ph.id = (
                SELECT id FROM price_history
                WHERE product_id = p.id ORDER BY checked_at DESC LIMIT 1
            )
            WHERE 1=1
        """
        params = []

        if site_slug:
            query += " AND s.slug = ?"
            params.append(site_slug)
        if set_code:
            query += " AND p.set_code = ?"
            params.append(set_code)
        if in_stock == '1':
            query += " AND ph.in_stock = 1"
        elif in_stock == '0':
            query += " AND (ph.in_stock = 0 OR ph.in_stock IS NULL)"
        if search:
            query += " AND p.name LIKE ?"
            params.append(f"%{search}%")

        if sort == 'price_asc':
            query += " ORDER BY CASE WHEN ph.price IS NULL THEN 1 ELSE 0 END, ph.price ASC"
        elif sort == 'price_desc':
            query += " ORDER BY ph.price DESC"
        elif sort == 'name':
            query += " ORDER BY p.name ASC"
        elif sort == 'recent':
            query += " ORDER BY ph.checked_at DESC"

        products = db.execute(query, params).fetchall()
        return jsonify([dict(p) for p in products]), 200

    except sqlite3.Error as e:
        logger.error(f"Erreur DB produits: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500


@app.route('/api/products/<int:product_id>/history')
def api_product_history(product_id):
    """Historique des prix d'un produit."""
    try:
        db = get_db()
        product = db.execute(
            """SELECT p.*, s.name as site_name, s.slug as site_slug
               FROM products p JOIN sites s ON p.site_id = s.id
               WHERE p.id = ?""",
            (product_id,)
        ).fetchone()

        if not product:
            return jsonify({"error": "Produit non trouve"}), 404

        history = db.execute(
            """SELECT price, in_stock, checked_at
               FROM price_history WHERE product_id = ?
               ORDER BY checked_at ASC""",
            (product_id,)
        ).fetchall()

        return jsonify({
            "product": dict(product),
            "history": [dict(h) for h in history],
        }), 200

    except sqlite3.Error as e:
        logger.error(f"Erreur DB historique: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500


@app.route('/api/sites')
def api_sites():
    """Liste des sites surveilles."""
    try:
        db = get_db()
        sites = db.execute("SELECT * FROM sites ORDER BY name").fetchall()
        return jsonify([dict(s) for s in sites]), 200
    except sqlite3.Error as e:
        logger.error(f"Erreur DB sites: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500


@app.route('/api/sets')
def api_sets():
    """Liste des sets One Piece detectes."""
    try:
        db = get_db()
        sets = db.execute(
            "SELECT DISTINCT set_code FROM products WHERE set_code IS NOT NULL ORDER BY set_code"
        ).fetchall()
        return jsonify([row['set_code'] for row in sets]), 200
    except sqlite3.Error as e:
        logger.error(f"Erreur DB sets: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500


@app.route('/api/stats')
def api_stats():
    """Statistiques du dashboard."""
    try:
        db = get_db()

        total = db.execute("SELECT COUNT(*) as c FROM products").fetchone()['c']
        in_stock = db.execute("""
            SELECT COUNT(DISTINCT p.id) as c FROM products p
            JOIN price_history ph ON ph.id = (
                SELECT id FROM price_history WHERE product_id = p.id
                ORDER BY checked_at DESC LIMIT 1
            ) WHERE ph.in_stock = 1
        """).fetchone()['c']
        total_sites = db.execute(
            "SELECT COUNT(*) as c FROM sites WHERE enabled = 1"
        ).fetchone()['c']

        avg_price = db.execute("""
            SELECT AVG(ph.price) as v FROM products p
            JOIN price_history ph ON ph.id = (
                SELECT id FROM price_history WHERE product_id = p.id
                ORDER BY checked_at DESC LIMIT 1
            ) WHERE ph.in_stock = 1 AND ph.price IS NOT NULL
        """).fetchone()['v']

        best_price = db.execute("""
            SELECT MIN(ph.price) as v FROM products p
            JOIN price_history ph ON ph.id = (
                SELECT id FROM price_history WHERE product_id = p.id
                ORDER BY checked_at DESC LIMIT 1
            ) WHERE ph.in_stock = 1 AND ph.price IS NOT NULL
        """).fetchone()['v']

        return jsonify({
            "total_products": total,
            "in_stock": in_stock,
            "out_of_stock": total - in_stock,
            "total_sites": total_sites,
            "avg_price": round(avg_price, 2) if avg_price else None,
            "best_price": best_price,
            "last_scan": last_scan_info,
        }), 200

    except sqlite3.Error as e:
        logger.error(f"Erreur DB stats: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500


@app.route('/api/scan', methods=['POST'])
def api_trigger_scan():
    """Declenche un scan manuel."""
    if last_scan_info['running']:
        return jsonify({"error": "Scan deja en cours"}), 409

    if last_scan_info.get('finished_at'):
        try:
            last_finish = datetime.fromisoformat(last_scan_info['finished_at'])
            if (datetime.now() - last_finish).total_seconds() < 60:
                return jsonify({"error": "Attendez 1 minute entre deux scans"}), 429
        except (ValueError, TypeError):
            pass

    thread = threading.Thread(target=run_scan, daemon=True)
    thread.start()
    return jsonify({"message": "Scan lance"}), 202


@app.route('/api/scan/status')
def api_scan_status():
    """Statut du dernier scan."""
    return jsonify(last_scan_info), 200


# ============================================================
# ROUTES PAGES
# ============================================================

@app.route('/')
def index():
    """Page d'accueil - Dashboard."""
    return render_template('index.html', version=__version__)


# ============================================================
# DEMARRAGE
# ============================================================

# Initialiser le scheduler au chargement du module (gunicorn compatible)
init_scheduler()

if __name__ == '__main__':
    if not DB_PATH.exists():
        logger.error(f"Base de donnees introuvable: {DB_PATH}")
        logger.info("Executez 'python setup.py' d'abord")
        exit(1)

    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    logger.info(f"OP Stock Monitor v{__version__} demarre sur le port {port}")
    app.run(debug=debug, port=port, host='0.0.0.0', use_reloader=False)
