"""
Application Flask - OP Stock Monitor
Surveillance de stock et prix de displays One Piece TCG
sur les principaux sites e-commerce francais.
"""

__version__ = '1.3.0'

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
    """Detecte le code du set One Piece (OP01, EB01, ST01...) dans le nom du produit."""
    match = re.search(r'(?:OP|op)[-\s]?(\d{2})', name)
    if match:
        return f"OP{match.group(1)}"
    match = re.search(r'(?:EB|eb)[-\s]?(\d{2})', name)
    if match:
        return f"EB{match.group(1)}"
    match = re.search(r'(?:ST|st)[-\s]?(\d{2})', name)
    if match:
        return f"ST{match.group(1)}"
    match = re.search(r'(?:PRB|prb)[-\s]?(\d{2})', name)
    if match:
        return f"PRB{match.group(1)}"
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
        'quatre empereurs': 'OP09',
        'royal blood': 'OP10',
        'sang royal': 'OP10',
        'swift as lightning': 'OP11',
        'poings vifs': 'OP11',
        'carrying on his will': 'OP12',
        'heritage du maitre': 'OP12',
        'h\u00e9ritage du ma\u00eetre': 'OP12',
        'successeurs': 'OP13',
        'azure sea': 'OP14',
        'sept de la mer': 'OP14',
        'heroines edition': 'EB03',
    }
    name_lower = name.lower()
    for set_name, code in set_names.items():
        if set_name in name_lower:
            return code
    return None


def is_french_display(name):
    """Verifie si le produit est un display unique en francais (pas case, pas bundle)."""
    name_lower = name.lower()
    if 'display' not in name_lower and 'boite de 24' not in name_lower and 'boite de 20' not in name_lower:
        return False
    # Exclure les langues non-francaises
    # Note : eviter '- en' et ' en ' qui matchent le francais "en francais"
    lang_excluded = ['(en)', '(eng)', '(jap)', '(jpn)',
                     'english', 'japanese', 'japonais', 'anglais']
    for ex in lang_excluded:
        if ex in name_lower:
            return False
    # Codes langue en suffixe (ex: "Display OP10 - JPN", "Display OP10 - EN")
    if re.search(r'[-\s](en|eng|jap|jpn)\s*$', name_lower):
        return False
    # Exclure les cases de displays (cartons de 10/12 displays)
    if 'case de' in name_lower or 'case -' in name_lower:
        return False
    # Exclure les bundles (display + autre produit)
    if 'bundle' in name_lower or ' + ' in name_lower:
        return False
    return True


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

def fetch_json(url):
    """Recupere du JSON depuis une URL."""
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'application/json',
    }
    try:
        response = http_requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except http_requests.RequestException as e:
        logger.error(f"Erreur requete JSON {url}: {e}")
        return None


def scrape_relictcg(url):
    """Scraper pour RelicTCG (Shopify JSON API)."""
    products = []
    data = fetch_json(url)
    if not data:
        return products

    for item in data.get('products', []):
        try:
            name = item.get('title', '')
            handle = item.get('handle', '')
            variants = item.get('variants', [])
            images = item.get('images', [])

            if not variants:
                continue

            variant = variants[0]
            price_str = variant.get('price', '0')
            price = float(price_str) if price_str else None
            in_stock = variant.get('available', False)
            image_url = images[0].get('src', '') if images else ''
            product_url = f"https://www.relictcg.com/products/{handle}"

            products.append({
                'name': name,
                'price': price if price and price > 0 else None,
                'in_stock': in_stock,
                'url': product_url,
                'image_url': image_url,
                'set_code': detect_set_code(name),
            })
        except Exception as e:
            logger.warning(f"Erreur parsing RelicTCG: {e}")

    logger.info(f"RelicTCG: {len(products)} produits trouves")
    return products


def scrape_destocktcg(url):
    """Scraper pour DestockTCG (site custom PHP).

    Structure HTML verifiee (fevrier 2026) :
      article.product-item-list
        > div.product-item-info
          > div.product-image-wrapper
            > span.product-item-label.outofstock  (si rupture)
            > a[href="/product/..."] > img.product-image
          > div.product-details
            > div.product-item-prices-wrapper
              > span.product-item-price          (prix normal)
              > span.product-item-price.promo    (prix promo)
              > span.product-item-price.base     (ancien prix barre)
            > div.product-item-name.text-truncate > a[href]
    """
    products = []
    html = fetch_page(url)
    if not html:
        return products

    soup = BeautifulSoup(html, 'html.parser')

    for item in soup.select('article.product-item-list'):
        try:
            name_el = item.select_one('.product-item-name a')
            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            if len(name) < 5:
                continue

            # Prix promo (prioritaire) puis prix normal
            price_el = (
                item.select_one('.product-item-price.promo')
                or item.select_one('.product-item-price')
            )
            price = parse_price(price_el.get_text() if price_el else '')

            link = name_el.get('href', '')
            if link and not link.startswith('http'):
                link = f"https://www.destocktcg.fr{link}"

            img_el = item.select_one('img.product-image')
            image = ''
            if img_el:
                image = img_el.get('data-src', img_el.get('src', ''))
                if image and not image.startswith('http'):
                    image = f"https://www.destocktcg.fr{image}"

            # Rupture indiquee par span.product-item-label.outofstock
            outofstock_label = item.select_one('.product-item-label.outofstock')
            in_stock = outofstock_label is None

            products.append({
                'name': name, 'price': price, 'in_stock': in_stock,
                'url': link, 'image_url': image, 'set_code': detect_set_code(name),
            })
        except Exception as e:
            logger.warning(f"Erreur parsing DestockTCG: {e}")

    logger.info(f"DestockTCG: {len(products)} produits trouves")
    return products


def scrape_woocommerce(url, base_url):
    """Scraper generique pour sites WooCommerce standard (ex: Guizette Family).

    Utilise les selecteurs WooCommerce classiques :
      ul.products > li.product
      .woocommerce-loop-product__title
      .woocommerce-Price-amount
    """
    products = []
    html = fetch_page(url)
    if not html:
        return products

    soup = BeautifulSoup(html, 'html.parser')

    for item in soup.select(
        'li.product, .product-item, .type-product, '
        '.products .product, ul.products > li'
    ):
        try:
            name_el = item.select_one(
                '.woocommerce-loop-product__title, h2, h3, .product-title'
            )
            link_el = item.select_one(
                'a.woocommerce-LoopProduct-link, a.woocommerce-loop-product__link, a[href]'
            )

            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            if len(name) < 5:
                continue

            sale_el = item.select_one('.price ins .woocommerce-Price-amount, .price ins .amount')
            regular_el = item.select_one('.price .woocommerce-Price-amount, .price .amount')
            price_el = item.select_one('.price')

            if sale_el:
                price = parse_price(sale_el.get_text())
            elif regular_el:
                price = parse_price(regular_el.get_text())
            elif price_el:
                price = parse_price(price_el.get_text())
            else:
                price = None

            link = ''
            if link_el:
                link = link_el.get('href', '')
                if link and not link.startswith('http'):
                    link = f"{base_url}{link}"

            img_el = item.select_one('img')
            image = ''
            if img_el:
                image = (
                    img_el.get('data-src')
                    or img_el.get('data-lazy-src')
                    or img_el.get('src', '')
                )
                if image and not image.startswith('http'):
                    image = f"{base_url}{image}"

            item_text = item.get_text(' ', strip=True).lower()
            out_of_stock = item.select_one('.out-of-stock, .soldout')
            add_to_cart = item.select_one('.add_to_cart_button, .ajax_add_to_cart')

            if out_of_stock or 'rupture' in item_text:
                in_stock = False
            elif add_to_cart:
                in_stock = True
            elif 'ajouter' in item_text or 'panier' in item_text:
                in_stock = True
            else:
                in_stock = 'indisponible' not in item_text

            products.append({
                'name': name, 'price': price, 'in_stock': in_stock,
                'url': link, 'image_url': image, 'set_code': detect_set_code(name),
            })
        except Exception as e:
            logger.warning(f"Erreur parsing WooCommerce ({base_url}): {e}")

    logger.info(f"WooCommerce ({base_url}): {len(products)} produits trouves")
    return products


def scrape_coindesbarons(url):
    """Scraper dedie au Coin des Barons (WooCommerce theme custom 'barons').

    Structure HTML verifiee (fevrier 2026) :
      div.products.lists__wrap
        > div.card-game  (ou .card-game.promo pour les promos)
          > a[href]  (lien englobant le visuel et le titre)
            > div.card-wrap
              > div.card-image > img
              > div.card-top > div.name  (categorie, ex: "One Piece")
              > div.card-right > p       (badge precommande + date)
              > div.card-price           (prix texte, ex: "269,99 EURO")
              > div.card-promo           (si promo, texte "Promo")
            > div.card-title > h2        (nom complet du produit)
          > div.buttons > div.links
            > button.add_to_cart_button  (si en stock)
            > a > span "Rupture de stock" (si rupture)
          > span.gtm4wp_productdata[data-gtm4wp_product_data]  (JSON structure)

    Strategie : on utilise le JSON GTM4WP en priorite (fiable), avec fallback HTML.
    """
    products = []
    html = fetch_page(url)
    if not html:
        return products

    soup = BeautifulSoup(html, 'html.parser')

    for item in soup.select('.card-game'):
        try:
            # Strategie 1 : JSON GTM4WP (le plus fiable)
            gtm_span = item.select_one('span.gtm4wp_productdata[data-gtm4wp_product_data]')
            if gtm_span:
                try:
                    gtm_data = json.loads(gtm_span.get('data-gtm4wp_product_data', '{}'))
                    name = gtm_data.get('item_name', '')
                    price = gtm_data.get('price')
                    stock_status = gtm_data.get('stockstatus', '')
                    product_link = gtm_data.get('productlink', '')
                    in_stock = stock_status == 'instock'

                    if name and len(name) >= 5:
                        img_el = item.select_one('.card-image img')
                        image = ''
                        if img_el:
                            image = (
                                img_el.get('data-src')
                                or img_el.get('data-lazy-src')
                                or img_el.get('src', '')
                            )

                        products.append({
                            'name': name,
                            'price': float(price) if price else None,
                            'in_stock': in_stock,
                            'url': product_link,
                            'image_url': image,
                            'set_code': detect_set_code(name),
                        })
                        continue
                except (json.JSONDecodeError, ValueError) as e:
                    logger.debug(f"GTM parse error, fallback HTML: {e}")

            # Strategie 2 : fallback parsing HTML
            name_el = item.select_one('.card-title h2')
            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            if len(name) < 5:
                continue

            # Prix dans div.card-price (texte direct, ex: "269,99 EURO")
            price_el = item.select_one('.card-price')
            price = None
            if price_el:
                # Le texte direct du div est le prix courant ;
                # un eventuel <p> enfant est l'ancien prix barre
                price_text = ''.join(
                    child for child in price_el.children if isinstance(child, str)
                ).strip()
                if price_text:
                    price = parse_price(price_text)
                else:
                    price = parse_price(price_el.get_text())

            # Lien produit : le <a> direct enfant de .card-game
            link_el = item.select_one('a[href]')
            link = link_el.get('href', '') if link_el else ''

            img_el = item.select_one('.card-image img')
            image = ''
            if img_el:
                image = (
                    img_el.get('data-src')
                    or img_el.get('data-lazy-src')
                    or img_el.get('src', '')
                )

            # Stock : bouton add_to_cart present = en stock ; "Rupture" dans .links = rupture
            links_div = item.select_one('.links')
            links_text = links_div.get_text(' ', strip=True).lower() if links_div else ''
            add_to_cart = item.select_one('.add_to_cart_button')

            if 'rupture' in links_text:
                in_stock = False
            elif add_to_cart:
                in_stock = True
            else:
                in_stock = False

            products.append({
                'name': name, 'price': price, 'in_stock': in_stock,
                'url': link, 'image_url': image, 'set_code': detect_set_code(name),
            })
        except Exception as e:
            logger.warning(f"Erreur parsing Coin des Barons: {e}")

    logger.info(f"Coin des Barons: {len(products)} produits trouves")
    return products


def scrape_philibert(url):
    """Scraper pour Philibert (PrestaShop 1.6-era theme sur philibertnet.com).

    Structure HTML verifiee (fevrier 2026) :
      ul.product_list.grid
        > li.ajax_block_product
          > div.wrapper_product[data-product-reference]
            > div.wrapper_product_1
              > a.product_img_link[href] > span.ratio-container > img
            > div.wrapper_product_2
              > div.labels
                > span.new-label          ("Nouveaute")
                > span.redprice-label     ("Prix rouge")
                > span.preorder-label     (precommande dispo)
                > span.comingsoon-label   (a venir, pas encore dispo)
              > p.s_title_block > a[href]  (titre du produit)
              > p.price_container > span.price  (prix)
            > div.wrapper_product_3
              > a.ajax_add_to_cart_button  (disabled="disabled" si non achetable)
              > a.lnk_view                (lien "Plus d'infos")

    Le dataLayer JS contient aussi les donnees produits (impressions).
    """
    products = []
    html = fetch_page(url)
    if not html:
        return products

    soup = BeautifulSoup(html, 'html.parser')

    # Strategie 1 : parsing HTML des blocs produit
    for item in soup.select('li.ajax_block_product'):
        try:
            name_el = item.select_one('.s_title_block a')
            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            if len(name) < 5:
                continue

            price_el = item.select_one('.price_container .price')
            price = parse_price(price_el.get_text() if price_el else '')

            link = name_el.get('href', '')
            if link and not link.startswith('http'):
                link = f"https://www.philibertnet.com{link}"

            img_el = item.select_one('.product_img_link img')
            image = ''
            if img_el:
                image = (
                    img_el.get('data-src')
                    or img_el.get('data-full-size-image-url')
                    or img_el.get('src', '')
                )

            # Disponibilite : on verifie le bouton d'ajout au panier
            # et les labels de statut
            add_btn = item.select_one('.ajax_add_to_cart_button')
            comingsoon = item.select_one('.comingsoon-label')
            preorder = item.select_one('.preorder-label')

            if comingsoon:
                # "A venir" - pas encore disponible
                in_stock = False
            elif add_btn and not add_btn.get('disabled'):
                # Bouton actif = achetable maintenant
                in_stock = True
            elif preorder:
                # Precommande avec "Dispo." = disponible en precommande
                details = preorder.select_one('.details')
                if details and 'dispo' in details.get_text(strip=True).lower():
                    in_stock = True
                else:
                    in_stock = False
            else:
                in_stock = False

            products.append({
                'name': name, 'price': price, 'in_stock': in_stock,
                'url': link, 'image_url': image, 'set_code': detect_set_code(name),
            })
        except Exception as e:
            logger.warning(f"Erreur parsing Philibert: {e}")

    # Si le parsing HTML n'a rien donne, fallback sur le dataLayer JS
    if not products:
        logger.info("Philibert: fallback sur dataLayer JS")
        for script in soup.find_all('script'):
            text = script.string or ''
            if '"impressions"' not in text:
                continue
            match = re.search(r'"impressions"\s*:\s*(\[.*?\])', text, re.DOTALL)
            if not match:
                continue
            try:
                impressions = json.loads(match.group(1))
                for imp in impressions:
                    name = imp.get('name', '')
                    if not name or len(name) < 5:
                        continue
                    price_val = imp.get('price')
                    link_slug = imp.get('link', '')
                    product_id = imp.get('id', '')
                    full_link = (
                        f"https://www.philibertnet.com/fr/one-piece-le-jeu-de-cartes/"
                        f"{product_id}-{link_slug}.html"
                    )
                    products.append({
                        'name': name,
                        'price': float(price_val) if price_val else None,
                        'in_stock': True,  # Le dataLayer ne donne pas le stock
                        'url': full_link,
                        'image_url': '',
                        'set_code': detect_set_code(name),
                    })
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Erreur parsing dataLayer Philibert: {e}")
            break

    logger.info(f"Philibert: {len(products)} produits trouves")
    return products


def scrape_ultrajeux(url):
    """Scraper pour UltraJeux (site custom).

    Structure HTML verifiee (fevrier 2026) :
      div.block_produit
        > div.contenu_block_produit_all
          > div.contenu
            > p.titre > a[href*="produit-"] > b  (nom du produit)
            > form
              > p.image > a > img.produit_scan    (image)
              > p.prix > span.prix                (prix, ex: "189,90 euro")
              > p.disponibilite > span > b         (Disponible / Indisponible)
    """
    products = []
    html = fetch_page(url)
    if not html:
        return products

    soup = BeautifulSoup(html, 'html.parser')

    for block in soup.select('div.block_produit'):
        try:
            title_link = block.select_one('p.titre a[href*="produit-"]')
            if not title_link:
                continue

            name = title_link.get_text(strip=True)
            if not name or len(name) < 5:
                continue

            href = title_link.get('href', '')
            full_url = href if href.startswith('http') else f"https://www.ultrajeux.com/{href.lstrip('/')}"

            price_el = block.select_one('p.prix span.prix')
            price = parse_price(price_el.get_text(strip=True)) if price_el else None

            stock_el = block.select_one('p.disponibilite')
            stock_text = stock_el.get_text(strip=True).lower() if stock_el else ''
            if 'indisponible' in stock_text:
                in_stock = False
            elif 'disponible' in stock_text:
                in_stock = True
            else:
                in_stock = price is not None

            img_el = block.select_one('img.produit_scan')
            image = img_el.get('src', '') if img_el else ''

            products.append({
                'name': name, 'price': price, 'in_stock': in_stock,
                'url': full_url, 'image_url': image, 'set_code': detect_set_code(name),
            })
        except Exception as e:
            logger.warning(f"Erreur parsing UltraJeux: {e}")

    logger.info(f"UltraJeux: {len(products)} produits trouves")
    return products


def scrape_antretemps(url):
    """Scraper pour L'Antre des Temps (CMS custom, antretemps.com).

    Structure HTML verifiee (fevrier 2026) :
      div.product_box
        > div.boite_produit1
          > div.bp.bp_content[idproduit]
            > div.bp_image > a > div.imageGabarit > div.pictureContainer > img[data-lazy]
          > div.bp_footer
            > h3.bp_designation > a[href]  (nom + lien)
            > div.bp_stock > span.articleDispo > a  (texte stock)
            > div.bp_prix                           (texte prix, ex: "18,90 euro")
    """
    products = []
    html = fetch_page(url)
    if not html:
        return products

    soup = BeautifulSoup(html, 'html.parser')

    for box in soup.select('div.product_box'):
        try:
            name_el = box.select_one('h3.bp_designation a')
            if not name_el:
                continue

            name = name_el.get_text(strip=True)
            if not name or len(name) < 5:
                continue

            link = name_el.get('href', '')

            price_el = box.select_one('.bp_prix')
            price = parse_price(price_el.get_text(strip=True)) if price_el else None

            stock_el = box.select_one('.bp_stock')
            stock_text = stock_el.get_text(strip=True).lower() if stock_el else ''
            in_stock = 'en stock' in stock_text or 'disponible' in stock_text

            img_el = box.select_one('img[data-lazy]')
            image = ''
            if img_el:
                image = img_el.get('data-lazy', '')

            products.append({
                'name': name, 'price': price, 'in_stock': in_stock,
                'url': link, 'image_url': image, 'set_code': detect_set_code(name),
            })
        except Exception as e:
            logger.warning(f"Erreur parsing Antre Temps: {e}")

    logger.info(f"Antre Temps: {len(products)} produits trouves")
    return products


# Registre des scrapers : slug -> fonction
SCRAPER_REGISTRY = {
    'relictcg': scrape_relictcg,
    'destocktcg': scrape_destocktcg,
    'coindesbarons': scrape_coindesbarons,
    'philibert': scrape_philibert,
    'ultrajeux': scrape_ultrajeux,
    'guizettefamily': lambda url: scrape_woocommerce(url, 'https://www.guizettefamily.com'),
    'antretemps': scrape_antretemps,
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

            displays = [p for p in site_products if is_french_display(p['name'])]
            logger.info(f"  {len(displays)}/{len(site_products)} sont des displays FR")

            saved = 0
            for product in displays:
                try:
                    save_product(conn, site['id'], product)
                    saved += 1
                except Exception as e:
                    logger.error(f"  Erreur sauvegarde: {e}")

            last_scan_info['results'][site_slug] = {
                'status': 'ok', 'count': saved, 'total_found': len(site_products),
                'displays_fr': len(displays),
            }
            logger.info(f"  {site['name']}: {saved} sauvegardes ({len(displays)} displays FR / {len(site_products)} total)")

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


@app.route('/api/products/grouped')
def api_products_grouped():
    """Produits regroupes par set_code avec comparaison des boutiques."""
    try:
        db = get_db()
        set_filter = request.args.get('set', '')
        stock_filter = request.args.get('in_stock', '')
        search = request.args.get('search', '')

        query = """
            SELECT p.id, p.name, p.set_code, p.url, p.image_url,
                   s.name as site_name, s.slug as site_slug,
                   ph.price, ph.in_stock, ph.checked_at
            FROM products p
            JOIN sites s ON p.site_id = s.id
            LEFT JOIN price_history ph ON ph.id = (
                SELECT id FROM price_history
                WHERE product_id = p.id ORDER BY checked_at DESC LIMIT 1
            )
            WHERE p.set_code IS NOT NULL
        """
        params = []

        if set_filter:
            query += " AND p.set_code = ?"
            params.append(set_filter)
        if stock_filter == '1':
            query += " AND ph.in_stock = 1"
        elif stock_filter == '0':
            query += " AND (ph.in_stock = 0 OR ph.in_stock IS NULL)"
        if search:
            query += " AND p.name LIKE ?"
            params.append(f"%{search}%")

        query += " ORDER BY p.set_code, ph.price ASC"
        rows = db.execute(query, params).fetchall()

        # Regrouper par set_code
        groups = {}
        for row in rows:
            r = dict(row)
            code = r['set_code']
            if code not in groups:
                groups[code] = {
                    'set_code': code,
                    'name': '',
                    'image_url': '',
                    'best_price': None,
                    'any_in_stock': False,
                    'shops': [],
                }
            g = groups[code]

            # Nom canonique : le plus court qui contient le set_code
            if not g['name'] or len(r['name']) < len(g['name']):
                g['name'] = r['name']

            # Image : prendre la premiere image non-vide de bonne qualite
            if not g['image_url'] and r['image_url']:
                g['image_url'] = r['image_url']
            elif r['image_url'] and 'mini/' not in r['image_url'] and 'mini/' in (g['image_url'] or ''):
                g['image_url'] = r['image_url']

            if r['in_stock']:
                g['any_in_stock'] = True
            if r['price'] and (g['best_price'] is None or r['price'] < g['best_price']):
                g['best_price'] = r['price']

            g['shops'].append({
                'site_name': r['site_name'],
                'site_slug': r['site_slug'],
                'price': r['price'],
                'in_stock': r['in_stock'],
                'url': r['url'],
                'product_id': r['id'],
                'checked_at': r['checked_at'],
            })

        result = sorted(groups.values(), key=lambda g: g['set_code'])

        # Trier les shops de chaque groupe par prix croissant
        for g in result:
            g['shops'].sort(key=lambda s: (
                0 if s['in_stock'] else 1,
                s['price'] if s['price'] else 99999,
            ))

        return jsonify(result), 200

    except sqlite3.Error as e:
        logger.error(f"Erreur DB produits groupes: {e}")
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
