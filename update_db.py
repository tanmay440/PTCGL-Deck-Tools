#!/usr/bin/env python3
"""
PTCGL Deck Optimizer - Database Updater (Segment 1)
====================================================

Run manually from the terminal whenever you want fresh data.

    python update_db.py            # fetch only what is not cached
    python update_db.py --force    # re-fetch everything

Requires internet access. Pulls card data from pokemontcg.io and meta
data from limitlesstcg.com. Writes everything to local JSON files under
``data/``. The Flask app (``app.py``) reads only from these files and
never touches the network.

Progress is printed to stdout with plain ``print()`` statements.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / 'data'
CARDS_DIR = DATA_DIR / 'cards'

POKEMON_TCG_API = 'https://api.pokemontcg.io/v2'
LIMITLESS_TCG_URL = 'https://limitlesstcg.com/tournaments'

# Polite delay between set fetches (seconds) to be nice to the API.
API_DELAY = 0.25


def slugify(name):
    """Convert a card name into a filename-safe slug."""
    s = (name or '').lower().strip()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')


# ---------------------------------------------------------------------------
# Card fetch
# ---------------------------------------------------------------------------

def fetch_legal_sets():
    """Fetch the list of currently Standard-legal sets from pokemontcg.io."""
    print('Fetching legal standard sets from pokemontcg.io ...')
    try:
        resp = requests.get(
            f'{POKEMON_TCG_API}/sets',
            params={'pageSize': 500},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        print(f'  ERROR fetching sets: {e}')
        return []

    legal_sets = []
    for s in payload.get('data', []):
        legalities = s.get('legalities', {}) or {}
        if legalities.get('standard') == 'Legal':
            legal_sets.append({
                'id': s.get('id'),
                'name': s.get('name'),
                'series': s.get('series'),
                'releaseDate': s.get('releaseDate'),
            })

    print(f'  Found {len(legal_sets)} legal standard sets')
    return legal_sets


def fetch_cards_for_set(set_id):
    """Fetch all cards belonging to a single set, handling pagination."""
    cards = []
    page = 1
    page_size = 250
    while True:
        try:
            resp = requests.get(
                f'{POKEMON_TCG_API}/cards',
                params={
                    'q': f'set.id:{set_id}',
                    'pageSize': page_size,
                    'page': page,
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f'  ERROR fetching cards for set {set_id} page {page}: {e}')
            break

        batch = data.get('data', []) or []
        cards.extend(batch)

        # If the batch was smaller than page_size we are at the end.
        if len(batch) < page_size:
            break
        page += 1
        if page > 20:  # safety guard
            break
    return cards


def normalize_card(raw):
    """Normalize a pokemontcg.io card dict into our local schema."""
    attacks = []
    for atk in raw.get('attacks', []) or []:
        damage = atk.get('damage') or '0'
        # damage strings can include "10x", "50+", etc. Keep digits only.
        damage_clean = re.sub(r'[^0-9]', '', str(damage)) or '0'
        attacks.append({
            'name': atk.get('name', ''),
            'damage': int(damage_clean),
            'cost': atk.get('convertedEnergyCost',
                            len(atk.get('cost', []) or [])),
            'text': atk.get('text', ''),
        })

    abilities = []
    for ab in raw.get('abilities', []) or []:
        abilities.append({
            'name': ab.get('name', ''),
            'text': ab.get('text', ''),
        })

    types = raw.get('types', []) or []
    primary_type = types[0] if types else 'Colorless'
    hp_str = raw.get('hp', '') or '0'
    hp_clean = re.sub(r'[^0-9]', '', str(hp_str)) or '0'
    legalities = raw.get('legalities', {}) or {}

    set_obj = raw.get('set', {}) or {}

    return {
        'name': raw.get('name', ''),
        'hp': int(hp_clean),
        'attacks': attacks,
        'abilities': abilities,
        'type': primary_type,
        'types': types,
        'supertype': raw.get('supertype', ''),
        'subtypes': raw.get('subtypes', []) or [],
        'evolvesFrom': raw.get('evolvesFrom', '') or '',
        'retreat_cost': raw.get('convertedRetreatCost', 0) or 0,
        'set_code': set_obj.get('id', ''),
        'number': raw.get('number', ''),
        'legal': legalities.get('standard') == 'Legal',
        'rarity': raw.get('rarity', ''),
    }


def fetch_all_cards(force=False):
    """Fetch every Standard-legal card from the API and write to disk."""
    sets = fetch_legal_sets()
    print(f'\nFetching cards for {len(sets)} sets ...')
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CARDS_DIR.mkdir(parents=True, exist_ok=True)

    set_ids = [s['id'] for s in sets]

    total_seen = 0
    written = 0
    skipped = 0
    errors = 0

    for i, sid in enumerate(set_ids, start=1):
        print(f'  [{i}/{len(set_ids)}] set {sid} ...', end=' ', flush=True)
        cards = fetch_cards_for_set(sid)
        new_for_set = 0
        for raw in cards:
            total_seen += 1
            name = raw.get('name', '')
            if not name:
                continue
            slug = slugify(name)
            path = CARDS_DIR / f'{slug}.json'
            if path.exists() and not force:
                skipped += 1
                continue
            try:
                normalized = normalize_card(raw)
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(normalized, f, indent=2, ensure_ascii=False)
                written += 1
                new_for_set += 1
            except Exception as e:
                errors += 1
                print(f'\n    ERROR writing {name}: {e}', flush=True)
        print(f'{new_for_set} new / {len(cards)} total')
        time.sleep(API_DELAY)

    # Write sets.json (just the list of set codes for fast lookup).
    sets_path = DATA_DIR / 'sets.json'
    with open(sets_path, 'w', encoding='utf-8') as f:
        json.dump(set_ids, f, indent=2)
    print(f'\nWrote {sets_path} with {len(set_ids)} set codes')

    print('\nCard fetch summary:')
    print(f'  Total cards seen:    {total_seen}')
    print(f'  Newly written:       {written}')
    print(f'  Skipped (cached):    {skipped}')
    print(f'  Errors:              {errors}')


# ---------------------------------------------------------------------------
# Meta scrape
# ---------------------------------------------------------------------------

def _default_meta():
    """A defensive fallback meta so the optimizer always has data to chew on."""
    return [
        {
            'name': 'Charizard ex',
            'prevalence_pct': 18.0,
            'archetype_type': 'Fire',
            'key_cards': ["Charizard ex", "Professor's Research"],
        },
        {
            'name': 'Lost City Box',
            'prevalence_pct': 12.0,
            'archetype_type': 'Colorless',
            'key_cards': ['Sableye', 'Lost City'],
        },
        {
            'name': 'Gardevoir ex',
            'prevalence_pct': 10.0,
            'archetype_type': 'Psychic',
            'key_cards': ['Gardevoir ex', 'Kieran'],
        },
        {
            'name': 'Dragapult ex',
            'prevalence_pct': 8.0,
            'archetype_type': 'Psychic',
            'key_cards': ['Dragapult ex', 'Professor\'s Research'],
        },
        {
            'name': 'Pidgeot ex Control',
            'prevalence_pct': 7.0,
            'archetype_type': 'Colorless',
            'key_cards': ['Pidgeot ex', 'Boss\'s Orders'],
        },
        {
            'name': 'Roaring Moon ex',
            'prevalence_pct': 6.0,
            'archetype_type': 'Darkness',
            'key_cards': ['Roaring Moon ex'],
        },
        {
            'name': 'Miraidon ex',
            'prevalence_pct': 6.0,
            'archetype_type': 'Lightning',
            'key_cards': ['Miraidon ex'],
        },
        {
            'name': 'Snorlax Stall',
            'prevalence_pct': 4.0,
            'archetype_type': 'Colorless',
            'key_cards': ['Snorlax'],
        },
    ]


def scrape_meta():
    """Scrape deck-archetype prevalence from limitlesstcg.com/tournaments."""
    print('\nScraping meta data from limitlesstcg.com ...')
    decks = []
    try:
        resp = requests.get(
            LIMITLESS_TCG_URL,
            timeout=30,
            headers={
                'User-Agent': 'Mozilla/5.0 (PTCGL Optimizer; local use only)',
                'Accept-Language': 'en-US,en;q=0.9',
            },
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        deck_counts = {}

        # Strategy 1: links to /decks/ pages usually sit inside a row that
        # also contains the deck count, e.g. "Charizard ex (15)" or
        # "Charizard ex 15 decks".
        links = soup.find_all('a', href=re.compile(r'/decks/'))
        for link in links:
            name = link.get_text(strip=True)
            if not name or len(name) > 80:
                continue
            if name.lower() in ('decks', 'view', 'more', 'all', 'home'):
                continue

            count = 0
            container = link.parent
            if container is not None:
                txt = container.get_text(' ', strip=True)
                # patterns: "Charizard ex (15)", "Charizard ex 15"
                m = re.search(r'\((\d+)\)', txt)
                if m:
                    count = int(m.group(1))
                else:
                    # strip the name and look for a trailing number
                    rest = txt.replace(name, '', 1).strip()
                    m = re.match(r'(\d+)', rest)
                    if m:
                        count = int(m.group(1))
            if count <= 0:
                count = 1
            deck_counts[name] = deck_counts.get(name, 0) + count

        # Strategy 2: any table rows that look like "deckname, count"
        if not deck_counts:
            for tr in soup.find_all('tr'):
                cells = tr.find_all(['td', 'th'])
                if len(cells) < 2:
                    continue
                name = cells[0].get_text(strip=True)
                if not name or len(name) > 80:
                    continue
                try:
                    count = int(re.sub(r'[^0-9]', '', cells[1].get_text()))
                except ValueError:
                    continue
                if count <= 0:
                    continue
                deck_counts[name] = deck_counts.get(name, 0) + count

        for name, count in deck_counts.items():
            decks.append({
                'name': name,
                'prevalence_pct': 0.0,
                'archetype_type': '',  # unknown without deeper scraping
                'key_cards': [],
                'source_count': count,
            })

        if not decks:
            print('  No decks parsed from page, falling back to default meta')
            decks = _default_meta()
        else:
            print(f'  Parsed {len(decks)} deck archetypes from page')

    except Exception as e:
        print(f'  ERROR scraping meta: {e}')
        decks = _default_meta()

    # Normalize to percentages.
    total = sum(int(d.get('source_count') or 1) for d in decks) or 1
    for d in decks:
        cnt = int(d.get('source_count') or 1)
        d['prevalence_pct'] = round(100 * cnt / total, 2)
        d.pop('source_count', None)
        # If archetype_type unknown, leave empty so the engine uses Colorless.

    meta_path = DATA_DIR / 'meta.json'
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(decks, f, indent=2, ensure_ascii=False)
    print(f'  Wrote {len(decks)} meta decks to {meta_path}')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='PTCGL Deck Optimizer - Database Updater',
    )
    parser.add_argument(
        '--force', action='store_true',
        help='Re-fetch all cards even if they are already cached on disk.',
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CARDS_DIR.mkdir(parents=True, exist_ok=True)

    print('=== PTCGL Deck Optimizer :: Database Updater ===\n')
    fetch_all_cards(force=args.force)
    scrape_meta()
    print('\n=== Update complete. You can now run `python app.py`. ===')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nAborted by user.', file=sys.stderr)
        sys.exit(1)
