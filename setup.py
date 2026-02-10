"""Script d'initialisation de la base de donnees OP Stock Monitor."""

import sqlite3
import json
from pathlib import Path
import os


DB_PATH = Path(os.getenv('DATABASE_PATH', 'data/app.db'))

INITIAL_SITES = [
    {
        'name': 'Cardmarket',
        'slug': 'cardmarket',
        'url': 'https://www.cardmarket.com',
        'search_urls': json.dumps([
            'https://www.cardmarket.com/fr/OnePiece/Products/Booster-Boxes',
        ]),
        'enabled': 1,
    },
    {
        'name': 'Pokecardex',
        'slug': 'pokecardex',
        'url': 'https://www.pokecardex.com',
        'search_urls': json.dumps([
            'https://www.pokecardex.com/catalogsearch/result/?q=display+one+piece',
        ]),
        'enabled': 1,
    },
    {
        'name': 'UltraJeux',
        'slug': 'ultrajeux',
        'url': 'https://www.ultrajeux.com',
        'search_urls': json.dumps([
            'https://www.ultrajeux.com/recherche.php?search=display+one+piece',
        ]),
        'enabled': 1,
    },
    {
        'name': 'Philibert',
        'slug': 'philibert',
        'url': 'https://www.philibert.net',
        'search_urls': json.dumps([
            'https://www.philibert.net/fr/recherche?controller=search&s=display+one+piece',
        ]),
        'enabled': 1,
    },
    {
        'name': 'LudiCorner',
        'slug': 'ludicorner',
        'url': 'https://www.ludicorner.com',
        'search_urls': json.dumps([
            'https://www.ludicorner.com/recherche?controller=search&s=display+one+piece',
        ]),
        'enabled': 1,
    },
    {
        'name': 'Dernier Bastion',
        'slug': 'dernier-bastion',
        'url': 'https://www.dernierbastion.fr',
        'search_urls': json.dumps([
            'https://www.dernierbastion.fr/recherche?controller=search&s=display+one+piece',
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

    for site in INITIAL_SITES:
        cursor.execute(
            """INSERT OR IGNORE INTO sites (name, slug, url, search_urls, enabled)
               VALUES (?, ?, ?, ?, ?)""",
            (site['name'], site['slug'], site['url'], site['search_urls'], site['enabled'])
        )

    conn.commit()
    conn.close()
    print(f"Base de donnees initialisee: {DB_PATH}")


if __name__ == '__main__':
    init_database()
    print("Setup termine!")
