#!/usr/bin/env python3
"""
PTCGL Deck Optimizer - Flask Web App (Segment 2)
================================================

The web UI for the optimizer. Reads **only** from local JSON files -
no network calls of any kind. All intelligence lives in ``optimizer.py``
and the modules under ``modules/``.

Routes:
    GET  /                  render home.html
    POST /optimize          run optimizer, render results.html
    POST /api/search        JSON search across data/cards/
    GET  /api/card/<name>   single-card lookup from local data
    POST /export            render export.html with raw paste text
"""

import json
import re
from pathlib import Path

from flask import Flask, render_template, request, jsonify

from optimizer import run_optimizer

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / 'data'
CARDS_DIR = DATA_DIR / 'cards'

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(name):
    s = (name or '').lower().strip()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')


def check_data(print_warning=True):
    """Return True if the local data directory has at least one card."""
    if not DATA_DIR.exists() or not CARDS_DIR.exists():
        if print_warning:
            print('No local data found. Run update_db.py first.')
        return False
    if not any(CARDS_DIR.iterdir()):
        if print_warning:
            print('No local data found. Run update_db.py first.')
        return False
    return True


def load_card(name):
    """Load a single card by name from local data."""
    if not name:
        return None
    path = CARDS_DIR / f'{slugify(name)}.json'
    if path.exists():
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    return None


def search_cards(query, limit=50):
    """Search local card data by name substring (case-insensitive)."""
    q = (query or '').lower().strip()
    if not q or not CARDS_DIR.exists():
        return []

    results = []
    seen_names = set()

    # First pass: matches against filename (fast).
    for path in CARDS_DIR.glob('*.json'):
        if q in path.stem.lower():
            try:
                with open(path, encoding='utf-8') as f:
                    card = json.load(f)
                name = card.get('name', '')
                if name in seen_names:
                    continue
                seen_names.add(name)
                card['_slug'] = path.stem
                results.append(card)
            except Exception:
                continue
            if len(results) >= limit:
                return results[:limit]

    # Second pass: matches against the in-file "name" field (slower but
    # catches names whose slug does not contain the substring).
    if len(results) < limit:
        for path in CARDS_DIR.glob('*.json'):
            try:
                with open(path, encoding='utf-8') as f:
                    card = json.load(f)
                name = (card.get('name') or '').lower()
                if q in name and card.get('name') not in seen_names:
                    seen_names.add(card.get('name'))
                    card['_slug'] = path.stem
                    results.append(card)
            except Exception:
                continue
            if len(results) >= limit:
                break

    return results[:limit]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def home():
    return render_template('home.html')


@app.route('/optimize', methods=['POST'])
def optimize():
    deck_list = request.form.get('deck_list', '')
    try:
        iterations = int(request.form.get('iterations', '5'))
    except (TypeError, ValueError):
        iterations = 5
    iterations = max(1, min(20, iterations))

    if not check_data(print_warning=False):
        return render_template(
            'results.html',
            error='No local data found. Run update_db.py first.',
            result=None,
        )

    result = run_optimizer(deck_list, iterations)
    return render_template('results.html', result=result, error=None)


@app.route('/api/search', methods=['POST'])
def api_search():
    payload = request.get_json(silent=True) or {}
    query = payload.get('query', '') or request.form.get('query', '')
    return jsonify(search_cards(query))


@app.route('/api/card/<name>')
def api_card(name):
    card = load_card(name)
    if card is None:
        return jsonify({'error': 'not found', 'name': name}), 404
    return jsonify(card)


@app.route('/export', methods=['POST'])
def export_view():
    """Render export.html with the raw PTCGL paste text."""
    text = request.form.get('export_text', '')
    return render_template('export.html', export_text=text)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    check_data()
    print('\nStarting PTCGL Deck Optimizer at http://127.0.0.1:5000 ...')
    print('Press Ctrl+C to stop.\n')
    app.run(debug=True, host='127.0.0.1', port=5000)
