"""
Strategy Engine
===============

Pure rule-based generation of human-readable strategy text. No network,
no LLM. Operates on local card dicts and the meta list.

Public API:
    generate_strategy(deck_list, meta_decks) -> dict
        {
            'setup_guide':     [str, ...],
            'attack_advisor':  [{attacker, attack_name, condition, priority}],
            'matchup_notes':   [{meta_deck, tag, note}],
            'core_cards':      [str, ...],
        }
"""

from modules.power_rater import TYPE_CHART, rate_card


# ---------------------------------------------------------------------------
# Evolution-family grouping (uses the on-disk evolvesFrom chain so that
#   Charmander / Charmeleon / Charizard are recognised as one family
#   regardless of how their names lexically split).
# ---------------------------------------------------------------------------

def _build_evolution_families(deck_list):
    """Return a list of families; each family is a list of Pokémon dicts.

    A family is a connected component in the evolvesFrom graph that
    contains at least one Pokémon from the deck.
    """
    pokemon = []
    for entry in deck_list:
        data = entry.get('data') or {}
        if data.get('supertype') != 'Pokémon':
            continue
        pokemon.append({
            'name': entry['name'],
            'count': entry.get('count', 0),
            'subtypes': data.get('subtypes', []) or [],
            'hp': data.get('hp', 0) or 0,
            'data': data,
        })

    by_name = {p['name']: p for p in pokemon}
    by_evolves_from = {}
    for p in pokemon:
        ef = (p['data'].get('evolvesFrom') or '').strip()
        if ef:
            by_evolves_from.setdefault(ef, []).append(p['name'])

    visited = set()
    families = []
    for p in pokemon:
        if p['name'] in visited:
            continue
        family_names = []
        queue = [p['name']]
        while queue:
            cur = queue.pop(0)
            if cur in visited:
                continue
            if cur not in by_name:
                continue
            visited.add(cur)
            family_names.append(cur)
            data = by_name[cur]['data']
            ef = (data.get('evolvesFrom') or '').strip()
            if ef and ef not in visited:
                queue.append(ef)
            for child in by_evolves_from.get(cur, []):
                if child not in visited:
                    queue.append(child)
        families.append([by_name[n] for n in family_names])
    return families


def _family_label(family):
    """Human-readable label for a family, using the highest-HP member's name."""
    if not family:
        return 'Unknown'
    top = max(family, key=lambda m: m['hp'])
    return top['name']


# ---------------------------------------------------------------------------
# Setup guide
# ---------------------------------------------------------------------------

def _build_setup_guide(pokemon_families, deck_list):
    steps = []
    has_basics = False
    has_stage2 = False

    for family in pokemon_families:
        basics = [m for m in family if 'Basic' in (m['subtypes'] or [])]
        stage2 = [m for m in family if 'Stage 2' in (m['subtypes'] or [])]
        if basics:
            has_basics = True
            for b in basics:
                steps.append(
                    f"Bench {b['name']} ({b['count']} in deck) as a "
                    f"starting Pokémon."
                )
        if stage2:
            has_stage2 = True
            label = _family_label(family)
            steps.append(
                f"Evolve the {label} line carefully — preserve Stage 2 "
                f"pieces or use Rare Candy."
            )

    if not has_basics:
        steps.append(
            "No Basic Pokémon detected — rely on search effects to put a "
            "Pokémon into play quickly."
        )
    if has_stage2:
        steps.append(
            "Plan Stage 2 evolution for turn 3+ — do not over-commit to "
            "early aggression."
        )

    primary_type = _primary_type(deck_list)
    if primary_type:
        steps.append(
            f"Attach {primary_type} energy to your primary attacker first; "
            f"spread only if you are attacking."
        )
    steps.append("Use Ball search cards turn 1 to find Basic Pokémon.")
    steps.append(
        "Use your draw Supporter turn 1 to set up your hand for the "
        "next two turns."
    )
    return steps


# ---------------------------------------------------------------------------
# Attack advisor
# ---------------------------------------------------------------------------

META_HP_THRESHOLDS = [200, 220, 230, 250, 270, 280, 300, 310, 320, 330, 340]


def _build_attack_advisor(deck_list, meta_decks):
    advisor = []
    for entry in deck_list:
        data = entry.get('data') or {}
        if data.get('supertype') != 'Pokémon':
            continue
        attacks = data.get('attacks', []) or []
        if not attacks:
            continue

        name = entry['name']
        if len(attacks) == 1:
            atk = attacks[0]
            dmg = atk.get('damage', 0) or 0
            priority = 'High' if dmg >= 200 else 'Medium'
            condition = (
                f"One-shots {dmg}+ HP targets."
                if dmg >= 200
                else f"Default attack ({dmg} damage)."
            )
            advisor.append({
                'attacker': name,
                'attack_name': atk.get('name', ''),
                'condition': condition,
                'priority': priority,
            })
            continue

        # Multiple attacks: pick best damage/energy and annotate.
        best = None
        best_ratio = -1
        for atk in attacks:
            cost = atk.get('cost', 0) or 0
            dmg = atk.get('damage', 0) or 0
            if cost <= 0:
                continue
            ratio = dmg / cost
            if ratio > best_ratio:
                best_ratio = ratio
                best = atk

        if best is None:
            continue

        dmg = best.get('damage', 0) or 0
        condition = f"Best damage per energy at {dmg} damage."
        priority = 'Medium'
        if dmg >= 280:
            condition = f"One-shots nearly every meta Pokémon ({dmg} damage)."
            priority = 'High'
        elif dmg >= 200:
            condition = f"One-shots most meta Pokémon ({dmg} damage)."
            priority = 'High'
        else:
            for th in META_HP_THRESHOLDS:
                if dmg * 2 >= th and dmg < th:
                    condition += f" 2HKOs {th} HP targets."
                    break

        advisor.append({
            'attacker': name,
            'attack_name': best.get('name', ''),
            'condition': condition,
            'priority': priority,
        })

    return advisor


# ---------------------------------------------------------------------------
# Matchup notes
# ---------------------------------------------------------------------------

def _build_matchup_notes(deck_list, meta_decks):
    notes = []
    primary_type = _primary_type(deck_list) or 'Colorless'
    avg_cost = _avg_attack_cost(deck_list)
    our_hp = _avg_pokemon_hp(deck_list)
    chart = TYPE_CHART.get(primary_type, {'strong': [], 'weak': []})

    for meta in meta_decks:
        name = meta.get('name', '')
        archetype = meta.get('archetype_type') or 'Colorless'
        prevalence = meta.get('prevalence_pct', 0) or 0

        if archetype in chart.get('strong', []):
            tag = 'Favorable'
            reason = (
                f"your {primary_type} type hits their {archetype} "
                f"for weakness"
            )
        elif archetype in chart.get('weak', []):
            tag = 'Unfavorable'
            reason = (
                f"their {archetype} type hits your {primary_type} "
                f"for weakness — play around it"
            )
        else:
            tag = 'Neutral'
            reason = (
                f"no inherent type advantage; rely on speed "
                f"(your avg attack cost {avg_cost:.1f}) and HP ({our_hp:.0f})"
            )

        note_text = f"[{tag}] vs {name} ({prevalence}% meta) — {reason}."
        notes.append({
            'meta_deck': name,
            'tag': tag,
            'note': note_text,
        })
    return notes


# ---------------------------------------------------------------------------
# Core card identification
# ---------------------------------------------------------------------------

def _identify_core_cards(deck_list, pokemon_families):
    """Pick the family whose highest-HP member is the strongest, then
    walk the evolvesFrom chain to collect every member of that family.

    Using ``top_hp`` (rather than copy-weighted totals) keeps the
    primary attacker stable when the optimizer adds lower-tier filler
    cards in later iterations.
    """
    core = []

    best_family = None
    best_top_hp = -1
    for family in pokemon_families:
        if not family:
            continue
        top_hp = max(m['hp'] for m in family)
        if top_hp > best_top_hp:
            best_top_hp = top_hp
            best_family = family

    if best_family:
        for m in best_family:
            if m['name'] not in core:
                core.append(m['name'])

    # Primary energy: a Basic Energy whose type matches the deck's
    # primary attacking type.
    primary_type = _primary_type(deck_list)
    for entry in deck_list:
        data = entry.get('data') or {}
        if data.get('supertype') != 'Energy':
            continue
        if 'Basic' not in (data.get('subtypes') or []):
            continue
        t = data.get('type') or primary_type
        if t == primary_type and entry['name'] not in core:
            core.append(entry['name'])

    # Key supporters: any draw Supporter with 3+ copies.
    for entry in deck_list:
        data = entry.get('data') or {}
        if data.get('supertype') != 'Trainer':
            continue
        if 'Supporter' not in (data.get('subtypes') or []):
            continue
        if entry.get('count', 0) >= 3 and entry['name'] not in core:
            core.append(entry['name'])

    return core


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

def _primary_type(deck_list):
    type_counts = {}
    for entry in deck_list:
        data = entry.get('data') or {}
        if data.get('supertype') != 'Pokémon':
            continue
        t = data.get('type') or 'Colorless'
        type_counts[t] = type_counts.get(t, 0) + entry.get('count', 0)
    if not type_counts:
        return None
    return max(type_counts, key=type_counts.get)


def _avg_attack_cost(deck_list):
    total_cost = 0
    total_attacks = 0
    for entry in deck_list:
        data = entry.get('data') or {}
        if data.get('supertype') != 'Pokémon':
            continue
        for atk in data.get('attacks', []) or []:
            cost = atk.get('cost', 0) or 0
            if cost > 0:
                total_cost += cost
                total_attacks += 1
    return (total_cost / total_attacks) if total_attacks else 0


def _avg_pokemon_hp(deck_list):
    """Average HP per slot, weighted by copy count."""
    total_hp = 0
    total = 0
    for entry in deck_list:
        data = entry.get('data') or {}
        if data.get('supertype') != 'Pokémon':
            continue
        hp = data.get('hp', 0) or 0
        count = entry.get('count', 0)
        if hp <= 0 or count <= 0:
            continue
        total_hp += hp * count
        total += count
    return (total_hp / total) if total else 0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_strategy(deck_list, meta_decks):
    """Generate a complete strategy dict for the given deck."""
    deck_list = deck_list or []
    meta_decks = meta_decks or []

    pokemon_families = _build_evolution_families(deck_list)

    setup_guide = _build_setup_guide(pokemon_families, deck_list)
    attack_advisor = _build_attack_advisor(deck_list, meta_decks)
    matchup_notes = _build_matchup_notes(deck_list, meta_decks)
    core_cards = _identify_core_cards(deck_list, pokemon_families)

    return {
        'setup_guide': setup_guide,
        'attack_advisor': attack_advisor,
        'matchup_notes': matchup_notes,
        'core_cards': core_cards,
    }
