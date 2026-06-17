#!/usr/bin/env python3
"""
PTCGL Deck Optimizer - Loop Controller
======================================

``run_optimizer`` is the single entry point that the Flask app calls.

It is deliberately self-contained: it does not import Flask, does not
touch the network, and only reads from local files. All intelligence is
delegated to the modules under ``modules/``.

The loop:
    1. Parse the user's deck-list string.
    2. Enrich each entry with its on-disk card data.
    3. Load ``data/meta.json``.
    4. For each iteration up to ``iterations``:
        - rate the deck
        - generate a strategy
        - identify the weakest cards
        - rebuild a refined 60-card deck
        - record iteration history
        - stop early if the new score does not improve
    5. Return a result dict that the Flask layer renders.

Progress is printed to stdout so the operator can watch the optimizer
work when the app is launched from a terminal.
"""

import json
import re
import sys
from pathlib import Path

from modules.power_rater import rate_deck, identify_weak_cards
from modules.strategy_engine import generate_strategy
from modules.deck_builder import build_deck, export_deck

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / 'data'
CARDS_DIR = DATA_DIR / 'cards'
META_PATH = DATA_DIR / 'meta.json'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(name):
    s = (name or '').lower().strip()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')


def load_meta():
    if not META_PATH.exists():
        print('[optimizer] WARNING: data/meta.json not found, using empty meta')
        return []
    try:
        with open(META_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f'[optimizer] WARNING: could not parse meta.json: {e}')
        return []


def load_card(name):
    """Load full card JSON by name from local data. Returns None if missing."""
    if not name:
        return None
    slug = slugify(name)
    path = CARDS_DIR / f'{slug}.json'
    if path.exists():
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Deck-list parsing
# ---------------------------------------------------------------------------

def parse_deck_list(text):
    """Parse a PTCGL export string into a list of card dicts.

    Each entry has ``count``, ``name``, ``set_code``, ``number``,
    ``section`` (one of 'Pokemon', 'Trainer', 'Energy' or None).
    """
    cards = []
    section = None

    if not text:
        return cards

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        low = line.lower()
        if low.startswith('pokémon:') or low.startswith('pokemon:'):
            section = 'Pokemon'
            continue
        if low.startswith('trainer:'):
            section = 'Trainer'
            continue
        if low.startswith('energy:'):
            section = 'Energy'
            continue

        # Try the full "count name set_code number" format first.
        parts = line.split()
        if not parts:
            continue

        # Skip stray section-count lines like "12" under a header.
        # A real card line has at least 4 tokens, or 3 tokens without set.
        entry = None
        try:
            head, set_code, number = line.rsplit(None, 2)
            count_str, name = head.split(None, 1)
            entry = {
                'count': int(count_str),
                'name': name,
                'set_code': set_code,
                'number': number,
                'section': section,
            }
        except ValueError:
            # Fall back to "count name" (or "count name junk").
            if len(parts) >= 2:
                try:
                    entry = {
                        'count': int(parts[0]),
                        'name': ' '.join(parts[1:]),
                        'set_code': '',
                        'number': '',
                        'section': section,
                    }
                except ValueError:
                    continue

        if entry is not None and entry['count'] > 0:
            cards.append(entry)

    return cards


def total_card_count(cards):
    return sum(c.get('count', 0) for c in cards)


def diff_cards(old, new):
    """Return (added, removed) name->count-delta tuples."""
    def to_map(deck):
        return {e['name']: e.get('count', 0) for e in deck}

    old_map = to_map(old)
    new_map = to_map(new)
    added, removed = [], []
    for name in set(old_map) | set(new_map):
        o = old_map.get(name, 0)
        n = new_map.get(name, 0)
        if n > o:
            added.append((name, n - o))
        elif n < o:
            removed.append((name, o - n))
    return added, removed


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_optimizer(deck_list_string, iterations=5):
    """Run the optimization loop and return a result dict.

    Returns dict with keys:
        iterations_run, scores, final_score, final_deck,
        strategy, export_string, history, error.
    """
    print(f'\n[optimizer] Parsing deck list ...', flush=True)
    parsed = parse_deck_list(deck_list_string)
    total = total_card_count(parsed)
    print(f'[optimizer] Parsed {len(parsed)} card lines, {total} total cards',
          flush=True)

    if total == 0:
        return {
            'iterations_run': 0,
            'scores': [],
            'final_score': 0.0,
            'final_deck': [],
            'strategy': None,
            'export_string': '',
            'history': [],
            'error': 'No cards were parsed from the input. '
                     'Check the PTCGL format.',
        }

    # Enrich with on-disk card data.
    enriched = []
    for entry in parsed:
        enriched.append({**entry, 'data': load_card(entry['name'])})

    meta_decks = load_meta()
    print(f'[optimizer] Loaded {len(meta_decks)} meta decks from disk',
          flush=True)

    deck = enriched
    prev_score = rate_deck(deck, meta_decks)
    print(f'[optimizer] Initial deck score: {prev_score:.2f}', flush=True)

    history = []
    final_strategy = None

    iterations = max(1, int(iterations))
    print(f'[optimizer] Running up to {iterations} iterations ...\n',
          flush=True)

    for i in range(iterations):
        # Generate strategy on current deck (before refinement).
        try:
            strategy = generate_strategy(deck, meta_decks)
            core = strategy.get('core_cards', [])
        except Exception as e:
            print(f'[optimizer] strategy_engine failed: {e}', flush=True)
            strategy = {
                'setup_guide': [],
                'attack_advisor': [],
                'matchup_notes': [],
                'core_cards': [],
            }
            core = []

        try:
            weak = identify_weak_cards(deck, meta_decks, n=5)
        except Exception as e:
            print(f'[optimizer] identify_weak_cards failed: {e}', flush=True)
            weak = []

        try:
            new_deck = build_deck(core, deck, meta_decks, {})
        except Exception as e:
            print(f'[optimizer] build_deck failed: {e}', flush=True)
            new_deck = deck

        try:
            new_score = rate_deck(new_deck, meta_decks)
        except Exception as e:
            print(f'[optimizer] rate_deck failed: {e}', flush=True)
            new_score = prev_score

        added, removed = diff_cards(deck, new_deck)
        delta = new_score - prev_score

        history.append({
            'iteration': i + 1,
            'score': round(new_score, 2),
            'previous_score': round(prev_score, 2),
            'delta': round(delta, 2),
            'cards_removed': [r[0] for r in removed],
            'cards_added': [a[0] for a in added],
        })

        print(
            f'[optimizer] Iter {i + 1:>2}: '
            f'prev={prev_score:6.2f} -> new={new_score:6.2f} '
            f'(delta={delta:+6.2f})  '
            f'+{len(added)} -{len(removed)}',
            flush=True,
        )

        if new_score <= prev_score:
            print(f'[optimizer] No improvement, stopping early.\n',
                  flush=True)
            break

        deck = new_deck
        prev_score = new_score
        final_strategy = strategy

    final_strategy = final_strategy or generate_strategy(deck, meta_decks)
    export_string = export_deck(deck)

    print(f'[optimizer] Final deck size: {total_card_count(deck)}',
          flush=True)
    print(f'[optimizer] Final score: {prev_score:.2f}\n', flush=True)

    return {
        'iterations_run': len(history),
        'scores': [h['score'] for h in history],
        'final_score': round(prev_score, 2),
        'final_deck': deck,
        'strategy': final_strategy,
        'export_string': export_string,
        'history': history,
        'error': None,
    }


if __name__ == '__main__':
    # Allow running the optimizer from the CLI as well:
    #     python optimizer.py path/to/deck.txt 5
    if len(sys.argv) < 2:
        print('Usage: python optimizer.py <deck_list.txt> [iterations]')
        sys.exit(1)
    deck_path = Path(sys.argv[1])
    iters = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    deck_text = deck_path.read_text(encoding='utf-8') if deck_path.exists() else deck_path.read_text()
    result = run_optimizer(deck_text, iters)
    print('\n--- Export ---')
    print(result['export_string'])
