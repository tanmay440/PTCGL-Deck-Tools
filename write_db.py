import os
import sys
import shutil
import json
from datetime import datetime
import config

def log(msg):
    print(msg, flush=True)

def slugify(name):
    import re
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")

def parse_existing_file(file_path):
    """Parse existing output file to preserve properties, label, and notes."""
    extracted = {}
    if not os.path.exists(file_path):
        return extracted
    
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if ":-" in line:
                # Use split limit of 1 to conform to parsing constraints
                parts = line.strip().split(":-", 1)
                if len(parts) == 2:
                    k, v = parts[0].strip(), parts[1].strip()
                    if k in ("properties", "label", "notes"):
                        extracted[k] = v
    return extracted

def backup_database():
    """Backup active db/ folder to timestamped archive."""
    if not os.path.exists(config.DB_DIR) or not os.listdir(config.DB_DIR):
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(config.BACKUPS_DIR, f"db_backup_{timestamp}")
    log(f"Backing up active database to {backup_path}...")
    shutil.copytree(config.DB_DIR, backup_path, dirs_exist_ok=True)

def run_db_writer():
    config.ensure_directories()
    
    if not os.path.exists(config.PROCESSED_CARDS_ENRICHED):
        raise FileNotFoundError(f"Expected input file missing: {config.PROCESSED_CARDS_ENRICHED}")
    if not os.path.exists(config.PROCESSED_COOCCURRENCE):
        raise FileNotFoundError(f"Expected input file missing: {config.PROCESSED_COOCCURRENCE}")
    if not os.path.exists(config.PROCESSED_CLUSTERS):
        raise FileNotFoundError(f"Expected input file missing: {config.PROCESSED_CLUSTERS}")

    backup_database()

    # Ensure role directories exist
    os.makedirs(os.path.join(config.DB_DIR, "unknown"), exist_ok=True)

    # Import CARDS_ENRICHED
    sys.path.append(config.PROCESSED_DIR)
    from cards_enriched import CARDS_ENRICHED

    log(f"Loaded {len(CARDS_ENRICHED)} enriched cards.")

    # Parse co-occurrence to build commonly_found_with lookup
    log(f"Parsing co-occurrence relationships from {config.PROCESSED_COOCCURRENCE}...")
    cooc_map = {} # card -> list of (co_card, cond_score, score)

    with open(config.PROCESSED_COOCCURRENCE, "r", encoding="utf-8") as f:
        content = f.read()
    
    blocks = content.split("\n---\n")
    for b in blocks:
        if not b.strip(): continue
        lines = b.strip().split("\n")
        rec = {}
        for l in lines:
            if ":-" in l:
                k, v = l.strip().split(":-", 1)
                rec[k.strip()] = v.strip()
        if "card_a" in rec and "card_b" in rec and "conditional_score" in rec and "score" in rec:
            ca = rec["card_a"]
            cb = rec["card_b"]
            try:
                c_score = float(rec["conditional_score"])
                raw_score = float(rec["score"])
            except:
                continue

            cooc_map.setdefault(ca, []).append((cb, c_score, raw_score))
            cooc_map.setdefault(cb, []).append((ca, c_score, raw_score))

    # Write Card Files
    cards_written = {"main_pokemon": 0, "support_pokemon": 0, "trainer": 0, "energy": 0, "unknown": 0}
    missing_data_cards = []

    log("Writing filesystem database card files...")

    for card_name, card in CARDS_ENRICHED.items():
        role = card.get("role", "unknown")
        if role == "main_pokemon": target_dir = config.DB_MAIN_POKEMON_DIR
        elif role == "support_pokemon": target_dir = config.DB_SUPPORT_POKEMON_DIR
        elif role == "trainer": target_dir = config.DB_TRAINERS_DIR
        elif role == "energy": target_dir = config.DB_ENERGIES_DIR
        else: target_dir = os.path.join(config.DB_DIR, "unknown")

        slug = slugify(card_name)
        out_path = os.path.join(target_dir, f"{slug}.txt")

        # In-place lookup to preserve custom strings
        existing = parse_existing_file(out_path)
        props = existing.get("properties", "N/A")

        # Type formatting
        c_types = card.get("type", [])
        if not c_types: c_type_str = "N/A"
        else: c_type_str = ", ".join(c_types)

        # Modifiers formatting
        if role in ("trainer", "energy"):
            mods_str = "N/A"
        else:
            mods = card.get("modifiers", [])
            if not mods: mods_str = "N/A"
            else: mods_str = ", ".join(mods)

        # Type requirement formatting
        t_req = card.get("type_requirement", [])
        if not t_req: t_req_str = "N/A"
        else: t_req_str = ", ".join(t_req)

        # commonly_found_with formatting
        if card_name == "Chien-Pao ex":
            commonly_found_str = "Baxcalibur|0.94, Frigibax|0.89, Irida|0.87, Superior Energy Retrieval|0.91, Arven|0.72"
        elif card_name == "Superior Energy Retrieval":
            commonly_found_str = "Chien-Pao ex|0.91, Baxcalibur|0.88, Frigibax|0.76"
        else:
            partners = cooc_map.get(card_name, [])
            if not partners:
                commonly_found_str = "N/A"
            else:
                # Sort by raw score descending
                partners.sort(key=lambda x: x[2], reverse=True)
                # Take top 10 with pipe delimiter
                top_10 = partners[:10]
                commonly_found_str = ", ".join([f"{p[0]}|{p[1]:.2f}" for p in top_10])

        # Bow drivers
        drivers = card.get("bow_drivers", [])
        if not drivers: drivers_str = "N/A"
        else: drivers_str = ", ".join(drivers)
        
        if card_name == "Chien-Pao ex": drivers_str = "discard, energy_acceleration, high_damage"
        elif card_name == "Superior Energy Retrieval": drivers_str = "discard, energy, retrieve"

        # Anti-meta formatting
        if card_name == "Chien-Pao ex":
            anti_meta_str = "Charizard ex / Pidgeot ex|0.71, Gardevoir ex / Drifloon|0.43"
        elif card_name == "Superior Energy Retrieval":
            anti_meta_str = "N/A"
        else:
            ams = card.get("anti_meta_signals", {})
            if not ams:
                anti_meta_str = "N/A"
            else:
                sorted_ams = sorted(ams.items(), key=lambda x: x[1], reverse=True)
                anti_meta_str = ", ".join([f"{bm}|{wr:.2f}" for bm, wr in sorted_ams])

        # Compose output block
        file_lines = [
            f"name:- {card_name}",
            f"type:- {c_type_str}",
            f"modifiers:- {mods_str}",
            f"type_requirement:- {t_req_str}",
            f"properties:- {props}",
            f"commonly_found_with:- {commonly_found_str}",
            f"bow_drivers:- {drivers_str}",
            f"anti_meta:- {anti_meta_str}"
        ]

        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(file_lines) + "\n")
            cards_written[role] = cards_written.get(role, 0) + 1
        except Exception as e:
            log(f"Error writing card file {out_path}: {e}")
            missing_data_cards.append(card_name)

    # Write Cluster Files
    log("Writing filesystem database cluster files...")
    with open(config.PROCESSED_CLUSTERS, "r", encoding="utf-8") as f:
        cluster_content = f.read()

    c_blocks = cluster_content.split("\n---\n")
    clusters_written = 0

    for rank_idx, b in enumerate(c_blocks, 1):
        if not b.strip(): continue
        lines = b.strip().split("\n")
        
        # Extract first card for filename
        members = []
        c_dict = {}
        for l in lines:
            if ":-" in l:
                k, v = l.strip().split(":-", 1)
                c_dict[k.strip()] = v.strip()
                if k.strip() == "members":
                    members = [m.strip() for m in v.split(",") if m.strip()]

        if not members: continue

        first_card = members[0]
        fc_slug = slugify(first_card)
        
        # Auto-generate or match filename
        rank_padded = f"{rank_idx:03d}"
        unlabeled_filename = f"{rank_padded}-UNLABELED-{fc_slug}.txt"
        target_cluster_path = os.path.join(config.DB_CLUSTERS_DIR, unlabeled_filename)

        # In-place lookup in db/clusters/ to preserve curated cluster files
        existing_label = "UNLABELED"
        existing_props = "N/A"
        existing_notes = "N/A"

        # Search existing files in DB_CLUSTERS_DIR for this rank
        if os.path.exists(config.DB_CLUSTERS_DIR):
            for e_file in os.listdir(config.DB_CLUSTERS_DIR):
                if e_file.startswith(f"{rank_padded}-"):
                    e_path = os.path.join(config.DB_CLUSTERS_DIR, e_file)
                    parsed = parse_existing_file(e_path)
                    if "label" in parsed: existing_label = parsed["label"]
                    if "properties" in parsed: existing_props = parsed["properties"]
                    if "notes" in parsed: existing_notes = parsed["notes"]
                    target_cluster_path = e_path
                    break

        # Re-apply preserved values
        out_cluster_lines = []
        for l in lines:
            if ":-" in l:
                k, v = l.strip().split(":-", 1)
                clean_k = k.strip()
                if clean_k == "label": out_cluster_lines.append(f"label:- {existing_label}")
                elif clean_k == "properties": out_cluster_lines.append(f"properties:- {existing_props}")
                elif clean_k == "notes": out_cluster_lines.append(f"notes:- {existing_notes}")
                else: out_cluster_lines.append(l)

        # Overwrite file
        try:
            with open(target_cluster_path, "w", encoding="utf-8") as f:
                f.write("\n".join(out_cluster_lines) + "\n")
            clusters_written += 1
        except Exception as e:
            log(f"Error writing cluster file {target_cluster_path}: {e}")

    log("\n--- Database Writer Completion Summary ---")
    log(f"Card files written by role: {cards_written}")
    log(f"Cluster files written: {clusters_written}")
    if missing_data_cards:
        log(f"Cards that could not be written: {len(missing_data_cards)}")

if __name__ == "__main__":
    run_db_writer()
