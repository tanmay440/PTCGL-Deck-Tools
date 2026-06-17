"""
Power Rater
===========

Pure rule-based scoring for individual cards and full decks.

Inputs are local card dicts (already loaded from ``data/cards/``) and
the local ``meta.json`` list. There are no network calls and no
external services.

Public API:
    rate_card(card)              -> float in [0, 100]
    rate_deck(deck_list, meta)   -> float in [0, 100]
    identify_weak_cards(...)     -> list of n lowest-rated entries
"""

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.resolve()
DATA_DIR = BASE_DIR / 'data'
CARDS_DIR = DATA_DIR / 'cards'


# ---------------------------------------------------------------------------
# Pokemon TCG type chart (best-effort approximation)
# ---------------------------------------------------------------------------

TYPE_CHART = {
    'Fire':      {'strong': ['Grass', 'Bug', 'Ice', 'Steel'],
                  'weak':   ['Water']},
    'Water':     {'strong': ['Fire', 'Ground', 'Rock'],
                  'weak':   ['Grass', 'Lightning']},
    'Grass':     {'strong': ['Water', 'Ground', 'Rock'],
                  'weak':   ['Fire', 'Ice', 'Flying', 'Poison']},
    'Lightning': {'strong': ['Water', 'Flying'],
                  'weak':   ['Ground']},
    'Psychic':   {'strong': ['Fighting', 'Poison'],
                  'weak':   ['Darkness', 'Bug', 'Ghost']},
    'Fighting':  {'strong': ['Lightning', 'Ice', 'Rock',
                             'Darkness', 'Steel'],
                  'weak':   ['Psychic', 'Flying', 'Fairy']},
    'Darkness':  {'strong': ['Psychic', 'Ghost'],
                  'weak':   ['Fighting', 'Bug', 'Fairy']},
    'Metal':     {'strong': ['Ice', 'Rock', 'Fairy'],
                  'weak':   ['Fire', 'Fighting', 'Ground']},
    'Fairy':     {'strong': ['Fighting', 'Dragon', 'Darkness'],
                  'weak':   ['Poison', 'Steel']},
    'Dragon':    {'strong': ['Dragon'],
                  'weak':   ['Fairy', 'Ice']},
    'Colorless': {'strong': [], 'weak': []},
    'Normal':    {'strong': [], 'weak': ['Fighting']},
}


# ---------------------------------------------------------------------------
# Format averages (lazily computed and cached)
# ---------------------------------------------------------------------------

_AVG_HP_CACHE = None


def _format_avg_hp():
    """Average HP across all Pokémon in ``data/cards/``, cached."""
    global _AVG_HP_CACHE
    if _AVG_HP_CACHE is not None:
        return _AVG_HP_CACHE
    if not CARDS_DIR.exists():
        _AVG_HP_CACHE = 130.0
        return _AVG_HP_CACHE
    total = 0
    count = 0
    for path in CARDS_DIR.glob('*.json'):
        try:
            with open(path, encoding='utf-8') as f:
                card = json.load(f)
        except Exception:
            continue
        if card.get('supertype') != 'Pokémon':
            continue
        hp = card.get('hp', 0) or 0
        if hp > 0:
            total += hp
            count += 1
    _AVG_HP_CACHE = (total / count) if count else 130.0
    return _AVG_HP_CACHE


def invalidate_cache():
    """Clear cached averages (call after ``update_db.py`` finishes)."""
    global _AVG_HP_CACHE
    _AVG_HP_CACHE = None


# ---------------------------------------------------------------------------
# Card-level scoring
# ---------------------------------------------------------------------------

def _best_attack(card):
    attacks = card.get('attacks', []) or []
    if not attacks:
        return None
    best = None
    best_ratio = -1.0
    for atk in attacks:
        cost = atk.get('cost', 0) or 0
        damage = atk.get('damage', 0) or 0
        if cost <= 0:
            continue
        ratio = damage / cost
        if ratio > best_ratio:
            best_ratio = ratio
            best = atk
    return best


def rate_card(card):
    """Score a single card on a 0-100 scale."""
    if not card:
        return 0.0

    score = 50.0

    # 1. Damage per energy ratio (the dominant signal for attackers).
    best = _best_attack(card)
    if best:
        cost = best.get('cost', 0) or 0
        damage = best.get('damage', 0) or 0
        if cost > 0:
            ratio = damage / cost  # e.g. 150 dmg / 3 energy = 50
            score += min(30.0, ratio * 0.5)
        if damage >= 200:
            score += 10.0  # one-shot potential
        if damage >= 280:
            score += 5.0   # top-end one-shot

    # 2. HP relative to the format average.
    hp = card.get('hp', 0) or 0
    if hp > 0:
        avg = _format_avg_hp()
        hp_delta = (hp - avg) / max(avg, 1)  # roughly -1 .. +1
        score += hp_delta * 15.0

    # 3. Ability bonus, scaled by keyword.
    abilities = card.get('abilities', []) or []
    if abilities:
        bonus = 0.0
        for ab in abilities:
            text = (ab.get('text') or '').lower()
            name = (ab.get('name') or '').lower()
            combined = text + ' ' + name
            if 'draw' in combined or 'search' in combined:
                bonus += 8.0
            elif 'damage' in combined or 'attack' in combined:
                bonus += 6.0
            elif 'heal' in combined or 'prevent' in combined:
                bonus += 4.0
            else:
                bonus += 3.0
        score += min(15.0, bonus)

    # 4. Retreat cost penalty.
    rc = card.get('retreat_cost', 0) or 0
    if rc == 0:
        pass
    elif rc == 1:
        score -= 3
    elif rc == 2:
        score -= 7
    elif rc == 3:
        score -= 15
    else:
        score -= 25

    return max(0.0, min(100.0, score))


# ---------------------------------------------------------------------------
# Trainer / Energy classification helpers
# ---------------------------------------------------------------------------

def _is_draw_supporter(card):
    """Return True if ``card`` is a draw-supporting Supporter."""
    if not card or card.get('supertype') != 'Trainer':
        return False
    if 'Supporter' not in (card.get('subtypes') or []):
        return False
    name = (card.get('name') or '').lower()
    text = (card.get('text') or '').lower()
    DRAW_KEYWORDS = [
        "professor's research", 'colress', 'cynthia', 'marnie', 'iono',
        'judge', 'professor', 'drayton', 'lacey',
    ]
    if any(k in name for k in DRAW_KEYWORDS):
        return True
    # Generic: any text mentioning draw + cards or searching the deck for cards.
    if ('draw' in text and 'card' in text):
        return True
    if 'search your deck' in text and ('supporter' in text or 'hand' in text):
        return True
    return False


def _is_ball_search(card):
    """Return True if ``card`` is a Ball-style search Item."""
    if not card or card.get('supertype') != 'Trainer':
        return False
    name = (card.get('name') or '').lower()
    text = (card.get('text') or '').lower()
    if 'ball' in name:
        return True
    if 'search your deck' in text and 'basic' in text:
        return True
    if 'pal pad' in name or 'battle catcher' in name:
        return False
    return False


def _is_switching(card):
    """Return True if ``card`` can switch the active Pokémon."""
    if not card or card.get('supertype') != 'Trainer':
        return False
    name = (card.get('name') or '').lower()
    text = (card.get('text') or '').lower()
    if name.strip() in ('switch', 'escape rope'):
        return True
    if 'scoop up net' in name or 'air balloon' in name or 'float stone' in name:
        return True
    if 'switch' in text and ('active' in text or 'benched' in text):
        return True
    return False


# ---------------------------------------------------------------------------
# Deck-level scoring
# ---------------------------------------------------------------------------

def _count_matches(deck, predicate):
    """Sum copy counts of all deck entries that match ``predicate(card)``."""
    total = 0
    for entry in deck:
        data = entry.get('data') or {}
        if predicate(data):
            total += entry.get('count', 0)
    return total


def rate_deck(deck_list, meta_decks):
    """Score an entire deck on a 0-100 scale."""
    deck_list = deck_list or []
    meta_decks = meta_decks or []

    if not deck_list:
        return 0.0

    # 1. Average card power across the 60-card slot.
    weighted_sum = 0.0
    total_count = 0
    for entry in deck_list:
        c = entry.get('count', 0)
        if c <= 0:
            continue
        score = rate_card(entry.get('data') or {})
        weighted_sum += score * c
        total_count += c
    avg_power = (weighted_sum / total_count) if total_count else 0.0

    # 2. Consistency score based on the standard supporter/ball/switch ranges.
    draw_count = _count_matches(deck_list, _is_draw_supporter)
    ball_count = _count_matches(deck_list, _is_ball_search)
    switch_count = _count_matches(deck_list, _is_switching)

    consistency = 50.0
    # Draw supporters: target 10-14
    if 10 <= draw_count <= 14:
        consistency += 15
    elif draw_count < 10:
        consistency -= (10 - draw_count) * 3
    else:
        consistency -= (draw_count - 14) * 4
    # Ball search: target 6-8
    if 6 <= ball_count <= 8:
        consistency += 12
    elif ball_count < 6:
        consistency -= (6 - ball_count) * 2
    else:
        consistency -= (ball_count - 8) * 2
    # Switching: target 2-4
    if 2 <= switch_count <= 4:
        consistency += 8
    elif switch_count < 2:
        consistency -= (2 - switch_count) * 4
    else:
        consistency -= (switch_count - 4) * 2

    consistency = max(0.0, min(100.0, consistency))

    # 3. Meta matchup score weighted by prevalence.
    meta_score = _meta_matchup_score(deck_list, meta_decks)

    # Weighted blend: 50% card power, 30% consistency, 20% meta.
    final = avg_power * 0.5 + consistency * 0.3 + meta_score * 0.2
    return max(0.0, min(100.0, final))


def _meta_matchup_score(deck_list, meta_decks):
    if not meta_decks:
        return 50.0

    # Our deck's primary type = the type with the most copies of Pokémon.
    type_counts = {}
    for entry in deck_list:
        data = entry.get('data') or {}
        if data.get('supertype') != 'Pokémon':
            continue
        t = data.get('type') or 'Colorless'
        type_counts[t] = type_counts.get(t, 0) + entry.get('count', 0)
    if not type_counts:
        return 50.0
    primary_type = max(type_counts, key=type_counts.get)

    weighted_sum = 0.0
    total_weight = 0.0
    chart = TYPE_CHART.get(primary_type, {'strong': [], 'weak': []})

    for meta in meta_decks:
        prevalence = meta.get('prevalence_pct', 0) or 0
        if prevalence <= 0:
            continue
        archetype = meta.get('archetype_type') or 'Colorless'
        if archetype in chart.get('strong', []):
            matchup = 70.0
        elif archetype in chart.get('weak', []):
            matchup = 30.0
        else:
            matchup = 50.0
        weighted_sum += matchup * prevalence
        total_weight += prevalence

    if total_weight == 0:
        return 50.0
    return weighted_sum / total_weight


# ---------------------------------------------------------------------------
# Weak-card identification
# ---------------------------------------------------------------------------

def identify_weak_cards(deck_list, meta_decks, n=5):
    """Return the n lowest-contributing deck entries, excluding core cards."""
    if not deck_list:
        return []

    core_names = set()

    # Top 3 Pokémon by power are treated as core.
    pokemon = [
        e for e in deck_list
        if (e.get('data') or {}).get('supertype') == 'Pokémon'
    ]
    pokemon_rated = sorted(
        pokemon,
        key=lambda e: rate_card(e.get('data') or {}),
        reverse=True,
    )
    for e in pokemon_rated[:3]:
        core_names.add(e['name'])

    # Basic Energy cards are core too.
    for e in deck_list:
        data = e.get('data') or {}
        if data.get('supertype') == 'Energy':
            subtypes = data.get('subtypes') or []
            if 'Basic' in subtypes:
                core_names.add(e['name'])

    candidates = []
    for e in deck_list:
        if e['name'] in core_names:
            continue
        score = rate_card(e.get('data') or {})
        candidates.append({
            'name': e['name'],
            'count': e.get('count', 0),
            'section': e.get('section'),
            'power': score,
        })

    candidates.sort(key=lambda c: (c['power'], c['name']))
    return candidates[:n]
