"""Script d'initialisation de la base de donnees OP Stock Monitor."""

import sqlite3
import json
from pathlib import Path
import os


DB_PATH = Path(os.getenv('DATABASE_PATH', 'data/app.db'))

INITIAL_SITES = [
    {
        'name': 'RelicTCG',
        'slug': 'relictcg',
        'url': 'https://www.relictcg.com',
        'search_urls': json.dumps([
            'https://www.relictcg.com/collections/display-boosters-one-piece/products.json',
        ]),
        'enabled': 1,
    },
    {
        'name': 'DestockTCG',
        'slug': 'destocktcg',
        'url': 'https://www.destocktcg.fr',
        'search_urls': json.dumps([
            'https://www.destocktcg.fr/jeux-de-cartes-a-collectionner/one-piece-card-game/boosters-et-boite-de-boosters-en-francais/',
        ]),
        'enabled': 1,
    },
    {
        'name': 'Le Coin des Barons',
        'slug': 'coindesbarons',
        'url': 'https://lecoindesbarons.com',
        'search_urls': json.dumps([
            'https://lecoindesbarons.com/les-tcg/cartes-onepiece/display-one-piece/',
        ]),
        'enabled': 1,
    },
    {
        'name': 'Philibert',
        'slug': 'philibert',
        'url': 'https://www.philibertnet.com',
        'search_urls': json.dumps([
            'https://www.philibertnet.com/fr/17214-one-piece-le-jeu-de-cartes',
        ]),
        'enabled': 1,
    },
    {
        'name': 'UltraJeux',
        'slug': 'ultrajeux',
        'url': 'https://www.ultrajeux.com',
        'search_urls': json.dumps([
            'https://www.ultrajeux.com/cat-0-1031-469-one-piece-card-game-boite-de-boosters-francais.html',
        ]),
        'enabled': 1,
    },
    {
        'name': 'Guizette Family',
        'slug': 'guizettefamily',
        'url': 'https://www.guizettefamily.com',
        'search_urls': json.dumps([
            'https://www.guizettefamily.com/categorie/one-piece/',
        ]),
        'enabled': 1,
    },
    {
        'name': "L'Antre des Temps",
        'slug': 'antretemps',
        'url': 'https://www.antretemps.com',
        'search_urls': json.dumps([
            'https://www.antretemps.com/jeux-de-cartes/one-piece-c899.html',
        ]),
        'enabled': 1,
    },
    {
        'name': 'Cards Hunter',
        'slug': 'cardshunter',
        'url': 'https://www.cardshunter.fr',
        'search_urls': json.dumps([
            'https://www.cardshunter.fr/categorie-produit/autres-tcg/one-piece/one-piece-tcg-scelle/',
        ]),
        'enabled': 1,
    },
]


def init_database():
    """Initialise la base de donnees avec le schema et les sites."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            url TEXT NOT NULL,
            search_urls TEXT,
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            set_code TEXT,
            url TEXT UNIQUE NOT NULL,
            image_url TEXT DEFAULT '',
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (site_id) REFERENCES sites(id)
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            price REAL,
            in_stock INTEGER DEFAULT 0,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        CREATE TABLE IF NOT EXISTS scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            finished_at TEXT,
            results TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_products_site ON products(site_id);
        CREATE INDEX IF NOT EXISTS idx_products_set ON products(set_code);
        CREATE INDEX IF NOT EXISTS idx_products_url ON products(url);
        CREATE INDEX IF NOT EXISTS idx_history_product ON price_history(product_id);
        CREATE INDEX IF NOT EXISTS idx_history_date ON price_history(checked_at);
    """)

    # Nettoyer les anciens sites et donnees orphelines
    existing_slugs = [s['slug'] for s in INITIAL_SITES]
    placeholders = ','.join('?' * len(existing_slugs))
    cursor.execute(
        f"DELETE FROM price_history WHERE product_id IN "
        f"(SELECT p.id FROM products p JOIN sites s ON p.site_id = s.id "
        f"WHERE s.slug NOT IN ({placeholders}))",
        existing_slugs,
    )
    cursor.execute(
        f"DELETE FROM products WHERE site_id IN "
        f"(SELECT id FROM sites WHERE slug NOT IN ({placeholders}))",
        existing_slugs,
    )
    cursor.execute(
        f"DELETE FROM sites WHERE slug NOT IN ({placeholders})",
        existing_slugs,
    )

    for site in INITIAL_SITES:
        cursor.execute(
            """INSERT OR IGNORE INTO sites (name, slug, url, search_urls, enabled)
               VALUES (?, ?, ?, ?, ?)""",
            (site['name'], site['slug'], site['url'], site['search_urls'], site['enabled'])
        )
        # Mettre a jour les URLs de recherche si elles ont change
        cursor.execute(
            "UPDATE sites SET search_urls = ?, url = ? WHERE slug = ?",
            (site['search_urls'], site['url'], site['slug'])
        )

    conn.commit()
    conn.close()
    print(f"Base de donnees initialisee: {DB_PATH}")


if __name__ == '__main__':
    init_database()
    print("Setup termine!")
