# OP Stock Monitor

Surveillance en temps réel des stocks et prix de displays One Piece TCG sur les principaux sites e-commerce français.

## Fonctionnalités

- **Surveillance multi-sites** : Cardmarket, Pokecardex, UltraJeux, Philibert, LudiCorner, Dernier Bastion
- **Scans automatiques** : toutes les 15 minutes (configurable)
- **Dashboard temps réel** : vue d'ensemble des produits, prix, disponibilités
- **Historique des prix** : graphiques d'évolution par produit (Chart.js)
- **Filtres avancés** : par site, par set (OP01-OP10+), par disponibilité
- **Thème clair/sombre** : préférence sauvegardée localement

## Sites surveillés

| Site | Type |
|------|------|
| Cardmarket | Marketplace |
| Pokecardex | Boutique TCG |
| UltraJeux | Boutique jeux |
| Philibert | Boutique jeux |
| LudiCorner | Boutique jeux |
| Dernier Bastion | Boutique TCG |

## Installation

```bash
cd /projects/op-stock-monitor

# Créer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt

# Configurer l'environnement
cp .env.example .env

# Initialiser la base de données
python setup.py
```

## Utilisation

```bash
python app.py
```

Accéder à http://localhost:5000

## API Endpoints

- `GET /api/health` - Health check (PyDeploy)
- `GET /api/products` - Liste des produits (filtres: site, set, in_stock, sort, search)
- `GET /api/products/<id>/history` - Historique des prix d'un produit
- `GET /api/sites` - Sites surveillés
- `GET /api/sets` - Sets One Piece détectés
- `GET /api/stats` - Statistiques du dashboard
- `POST /api/scan` - Déclencher un scan manuel
- `GET /api/scan/status` - Statut du dernier scan

## Configuration

Variables d'environnement dans `.env` :

| Variable | Description | Défaut |
|----------|-------------|--------|
| `DATABASE_PATH` | Chemin base SQLite | `data/app.db` |
| `SCAN_INTERVAL` | Intervalle de scan (minutes) | `15` |
| `REQUEST_TIMEOUT` | Timeout requêtes HTTP (secondes) | `30` |
| `PORT` | Port du serveur | `5000` |
| `DEBUG` | Mode debug Flask | `False` |

## Ajouter un nouveau site

1. Ajouter la configuration dans `SITES_CONFIG` (app.py)
2. Créer la fonction scraper `scrape_nomsite(url)`
3. Enregistrer dans `SCRAPER_REGISTRY`
4. Ajouter le site dans `INITIAL_SITES` (setup.py)
5. Relancer `python setup.py` pour insérer le site en BDD

## Déploiement PyDeploy

Ce projet est conçu pour être déployé via PyDeploy.
Le push sur `main` déclenche le redéploiement automatique.
