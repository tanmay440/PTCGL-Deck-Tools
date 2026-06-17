"""
Deck Builder
============

Fill and refine a 60-card deck around a set of core cards.

Public API:
    build_deck(core_cards, deck_list, meta_decks, power_ratings) -> list
    export_deck(deck_list) -> str (PTCGL paste format)
"""

import json
import re
from pathlib import Path

from modules.power_rater import (
    rate_card,
    _is_draw_supporter,
    _is_ball_search,
    _is_switching,
)

BASE_DIR = Path(__file__).parent.parent.resolve()
DATA_DIR = BASE_DIR / 'data'
CARDS_DIR = DATA_DIR / 'cards'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(name):
    s = (name or '').lower().strip()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')


_CARDS_CACHE = None


def _all_cards():
    """Load every card from ``data/cards/`` once, then cache."""
    global _CARDS_CACHE
    if _CARDS_CACHE is None:
        cards = []
        if CARDS_DIR.exists():
            for path in CARDS_DIR.glob('*.json'):
                try:
                    with open(path, encoding='utf-8') as f:
                        cards.append(json.load(f))
                except Exception:
                    continue
        _CARDS_CACHE = cards
    return _CARDS_CACHE


def invalidate_cache():
    """Clear cached card list (call after running ``update_db.py``)."""
    global _CARDS_CACHE
    _CARDS_CACHE = None


def _primary_type(deck_list):
    type_counts = {}
    for entry in deck_list:
        data = entry.get('data') or {}
        if data.get('supertype') != 'Pokémon':
            continue
        t = data.get('type') or 'Colorless'
        type_counts[t] = type_counts.get(t, 0) + entry.get('count', 0)
    if not type_counts:
        return 'Colorless'
    return max(type_counts, key=type_counts.get)


def _total_count(deck):
    return sum(e.get('count', 0) for e in deck)


def _add_count(deck, name, n, section=None, data=None):
    for e in deck:
        if e['name'] == name:
            e['count'] += n
            if data is not None and not e.get('data'):
                e['data'] = data
            return
    new = {
        'name': name,
        'count': max(0, n),
        'set_code': '',
        'number': '',
        'section': section,
    }
    if data is not None:
        new['data'] = data
    deck.append(new)


def _section_count(deck, predicate):
    c = 0
    for e in deck:
        data = e.get('data') or {}
        if predicate(data):
            c += e.get('count', 0)
    return c


def _cap_illegal(deck):
    """Enforce the 4-copy limit on every non-Basic-Energy card."""
    for e in deck:
        data = e.get('data') or {}
        if data.get('supertype') == 'Energy':
            subtypes = data.get('subtypes', []) or []
            if 'Basic' in subtypes:
                continue  # unlimited basic energy
        if e.get('count', 0) > 4:
            e['count'] = 4


# ---------------------------------------------------------------------------
# Evolution line completion
# ---------------------------------------------------------------------------

def _evolutions_in_deck(core_names):
    """Return the full set of evolution-line Pokémon names for ``core_names``."""
    all_cards = _all_cards()
    by_name = {c.get('name', ''): c for c in all_cards}
    by_evolves_from = {}
    for nm, c in by_name.items():
        ef = (c.get('evolvesFrom') or '').strip()
        if ef:
            by_evolves_from.setdefault(ef, []).append(nm)

    line = set()
    visited = set()

    def visit(name):
        if not name or name in visited:
            return
        visited.add(name)
        line.add(name)
        card = by_name.get(name)
        if card:
            ef = (card.get('evolvesFrom') or '').strip()
            if ef:
                visit(ef)
        for child in by_evolves_from.get(name, []):
            visit(child)

    for cn in core_names or []:
        visit(cn)
    return [n for n in line if n]


def _best_card_by_name(name):
    """Look up a card by name in the cached card list."""
    for c in _all_cards():
        if c.get('name') == name:
            return c
    return None


# ---------------------------------------------------------------------------
# build_deck
# ---------------------------------------------------------------------------

def build_deck(core_cards, deck_list, meta_decks, power_ratings):
    """Refill the deck to exactly 60 cards following the spec's priority."""
    deck = []
    for entry in (deck_list or []):
        # shallow copy so we don't mutate the caller's deck.
        deck.append(dict(entry))

    core_cards = core_cards or []

    # Legality: enforce 4-copy cap on non-Basic-Energy.
    _cap_illegal(deck)

    # Trim over-60 by removing non-core, non-energy cards first.
    while _total_count(deck) > 60:
        candidates = [
            e for e in deck
            if e['name'] not in core_cards
            and (e.get('data') or {}).get('supertype') != 'Energy'
            and e.get('count', 0) > 0
        ]
        if not candidates:
            break
        candidates.sort(
            key=lambda e: rate_card(e.get('data') or {}),
        )
        candidates[0]['count'] -= 1
        if candidates[0]['count'] == 0:
            deck.remove(candidates[0])
    deck = [e for e in deck if e.get('count', 0) > 0]

    primary_type = _primary_type(deck)
    all_cards = _all_cards()

    # Priority 1 — Complete evolution lines for any core Pokémon.
    evo_names = _evolutions_in_deck(core_cards)
    for evo in evo_names:
        if not any(e['name'] == evo for e in deck):
            card_data = _best_card_by_name(evo)
            if card_data and card_data.get('legal'):
                _add_count(deck, evo, 1, 'Pokemon', card_data)

    # Priority 2 — Draw supporters: target 12 (mid of 10-14).
    if _total_count(deck) < 60:
        target = 12
        have = _section_count(deck, _is_draw_supporter)
        need = max(0, target - have)
        if need > 0:
            candidates = []
            for c in all_cards:
                if c.get('supertype') != 'Trainer':
                    continue
                if 'Supporter' not in (c.get('subtypes') or []):
                    continue
                if not _is_draw_supporter(c):
                    continue
                if not c.get('legal'):
                    continue
                if any(e['name'] == c.get('name') for e in deck):
                    continue
                candidates.append((rate_card(c), c))
            candidates.sort(key=lambda x: -x[0])
            added = 0
            for rating, c in candidates:
                if added >= need:
                    break
                nm = c['name']
                add = min(4, need - added)
                _add_count(deck, nm, add, 'Trainer', c)
                added += add

    # Priority 3 — Ball search: target 7 (mid of 6-8).
    if _total_count(deck) < 60:
        target = 7
        have = _section_count(deck, _is_ball_search)
        need = max(0, target - have)
        if need > 0:
            candidates = []
            for c in all_cards:
                if c.get('supertype') != 'Trainer':
                    continue
                if not _is_ball_search(c):
                    continue
                if not c.get('legal'):
                    continue
                if any(e['name'] == c.get('name') for e in deck):
                    continue
                candidates.append((rate_card(c), c))
            candidates.sort(key=lambda x: -x[0])
            added = 0
            for rating, c in candidates:
                if added >= need:
                    break
                nm = c['name']
                add = min(4, need - added)
                _add_count(deck, nm, add, 'Trainer', c)
                added += add

    # Priority 4 — Switching: target 3 (mid of 2-4).
    if _total_count(deck) < 60:
        target = 3
        have = _section_count(deck, _is_switching)
        need = max(0, target - have)
        if need > 0:
            candidates = []
            for c in all_cards:
                if c.get('supertype') != 'Trainer':
                    continue
                if not _is_switching(c):
                    continue
                if not c.get('legal'):
                    continue
                if any(e['name'] == c.get('name') for e in deck):
                    continue
                candidates.append((rate_card(c), c))
            candidates.sort(key=lambda x: -x[0])
            added = 0
            for rating, c in candidates:
                if added >= need:
                    break
                nm = c['name']
                add = min(4, need - added)
                _add_count(deck, nm, add, 'Trainer', c)
                added += add

    # Priority 5 — Highest-rated Pokémon matching primary type.
    if _total_count(deck) < 60:
        need = 60 - _total_count(deck)
        candidates = []
        for c in all_cards:
            if c.get('supertype') != 'Pokémon':
                continue
            if not c.get('legal'):
                continue
            if (c.get('type') or 'Colorless') != primary_type:
                continue
            if any(e['name'] == c.get('name') for e in deck):
                continue
            candidates.append((rate_card(c), c))
        candidates.sort(key=lambda x: -x[0])
        added = 0
        for rating, c in candidates:
            if added >= need:
                break
            nm = c['name']
            add = min(4, need - added)
            _add_count(deck, nm, add, 'Pokemon', c)
            added += add

    # Priority 6 — Energy to match the primary attacker's avg cost, cap 12.
    if _total_count(deck) < 60:
        avg_cost = _avg_primary_attacker_cost(deck)
        # Target between 8 and 12, biased by the attacker's average cost.
        target_energy = max(8, min(12, avg_cost + 5))
        energy_have = _section_count(
            deck,
            lambda c: c.get('supertype') == 'Energy'
            and 'Basic' in (c.get('subtypes') or []),
        )
        need_basic = max(0, target_energy - energy_have)
        if need_basic > 0:
            energy_card = _find_basic_energy(primary_type, all_cards)
            if energy_card:
                nm = energy_card['name']
                add = min(need_basic, 60 - _total_count(deck))
                if add > 0:
                    _add_count(deck, nm, add, 'Energy', energy_card)

    # If we are still short, fill with the highest-rated remaining cards.
    if _total_count(deck) < 60:
        need = 60 - _total_count(deck)
        candidates = []
        for c in all_cards:
            if not c.get('legal'):
                continue
            if any(e['name'] == c.get('name') for e in deck):
                continue
            candidates.append((rate_card(c), c))
        candidates.sort(key=lambda x: -x[0])
        added = 0
        for rating, c in candidates:
            if added >= need:
                break
            nm = c['name']
            add = min(4, need - added)
            section = (
                'Pokemon' if c.get('supertype') == 'Pokémon'
                else 'Trainer' if c.get('supertype') == 'Trainer'
                else 'Energy'
            )
            _add_count(deck, nm, add, section, c)
            added += add

    # Trim if we overshot 60 (safety net).
    while _total_count(deck) > 60:
        candidates = [
            e for e in deck
            if e['name'] not in core_cards
            and (e.get('data') or {}).get('supertype') != 'Energy'
            and e.get('count', 0) > 0
        ]
        if not candidates:
            break
        candidates.sort(
            key=lambda e: rate_card(e.get('data') or {}),
        )
        candidates[0]['count'] -= 1
        if candidates[0]['count'] == 0:
            deck.remove(candidates[0])

    deck = [e for e in deck if e.get('count', 0) > 0]
    return deck


def _avg_primary_attacker_cost(deck_list):
    if not deck_list:
        return 2
    best = None
    best_score = -1
    for entry in deck_list:
        data = entry.get('data') or {}
        if data.get('supertype') != 'Pokémon':
            continue
        score = entry.get('count', 0) * (data.get('hp', 0) or 0)
        if score > best_score:
            best_score = score
            best = entry
    if not best:
        return 2
    attacks = (best.get('data') or {}).get('attacks', []) or []
    costs = [a.get('cost', 0) or 0 for a in attacks if (a.get('cost', 0) or 0) > 0]
    if not costs:
        return 2
    return round(sum(costs) / len(costs))


def _find_basic_energy(energy_type, all_cards):
    """Find a Basic Energy card matching the given type (best effort)."""
    candidates = []
    for c in all_cards:
        if c.get('supertype') != 'Energy':
            continue
        if 'Basic' not in (c.get('subtypes') or []):
            continue
        if not c.get('legal'):
            continue
        t = c.get('type') or ''
        if energy_type and t and t != energy_type:
            continue
        candidates.append(c)
    if not candidates:
        # Fall back to ANY legal basic energy if a typed match wasn't found.
        for c in all_cards:
            if c.get('supertype') != 'Energy':
                continue
            if 'Basic' not in (c.get('subtypes') or []):
                continue
            if c.get('legal'):
                return c
        return None
    # Prefer name that explicitly mentions the type (e.g. "Fire Energy").
    for c in candidates:
        nm = (c.get('name') or '').lower()
        if energy_type and energy_type.lower() in nm and 'energy' in nm:
            return c
    return candidates[0]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_deck(deck_list):
    """Return a PTCGL paste-format string."""
    groups = {'Pokemon': [], 'Trainer': [], 'Energy': []}

    for entry in deck_list or []:
        section = entry.get('section') or _guess_section(entry)
        if section not in groups:
            section = 'Trainer'
        data = entry.get('data') or {}
        set_code = entry.get('set_code') or data.get('set_code') or ''
        number = entry.get('number') or data.get('number') or ''
        groups[section].append(
            (entry['count'], entry['name'], set_code, number)
        )

    for k in groups:
        groups[k].sort(key=lambda x: x[1].lower())

    lines = []
    for section in ('Pokemon', 'Trainer', 'Energy'):
        items = groups[section]
        if not items:
            continue
        total = sum(c for c, _, _, _ in items)
        lines.append(f'{section}: {total}')
        for count, name, set_code, number in items:
            tail = f' {set_code} {number}' if set_code and number else ''
            lines.append(f'{count} {name}{tail}'.strip())
        lines.append('')

    return '\n'.join(lines).strip()


def _guess_section(entry):
    data = entry.get('data') or {}
    supertype = data.get('supertype', '')
    if supertype == 'Pokémon':
        return 'Pokemon'
    if supertype == 'Trainer':
        return 'Trainer'
    if supertype == 'Energy':
        return 'Energy'
    name = (entry.get('name') or '').lower()
    if 'energy' in name and 'basic' in name:
        return 'Energy'
    return 'Trainer'
