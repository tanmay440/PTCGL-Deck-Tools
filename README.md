# Pokémon TCG Data Harvester & BoW Pipeline

A standalone offline batch pipeline in Python for harvesting Pokémon TCG tournament data, enriching cards with feature vectors via Bag-of-Words (BoW) NLP parsing, computing weighted co-occurrence relationships, clustering cards into functional units, and writing a highly resilient human-readable flat-file database.

---

## Directory Structure

### Pipeline Working Directories
- `cache/`
  - `cards/`: Raw card attributes from `pokemontcg.io` cached as clean `key:- value` plain text files.
  - `tournaments/`: Raw text dumps of tournament metadata.
  - `standings/`: Raw text standings records and non-mirror matchup statistics by tournament ID.
- `processed/`
  - `decklists.txt`: Flat plain text file, one line per player's complete decklist.
  - `cards_enriched.py`: Python module declaring a master `CARDS_ENRICHED` dictionary lookup.
  - `cooccurrence.txt`: Human-readable ranked list of card pairs and raw co-occurrence scores.
  - `clusters.txt`: Surviving functional clusters separated by structural dividers (`---`).
  - `clusters_staples.txt`: Universal staple clusters filtered by ubiquity (>85% appearance rate) for manual review.
  - `matchup_matrix.txt`: Human-readable archetype vs archetype winrates.

### Deliverable Output Database
The final deliverable database is written to `db/`:
- `db/main_pokemon/` (e.g. `chien-pao-ex.txt`, `charizard-ex.txt`)
- `db/support_pokemon/` (e.g. `baxcalibur.txt`, `comfey.txt`)
- `db/trainers/` (e.g. `superior-energy-retrieval.txt`, `ultra-ball.txt`)
- `db/energies/` (e.g. `basic-water-energy.txt`, `jet-energy.txt`)
- `db/clusters/` (e.g. `001-UNLABELED-chien-pao-ex.txt`)
- `backups/`: Automated timestamped archive backups created prior to any structural filesystem re-writes.

---

## Pipeline Scripts

### 1. `config.py`
Centralized configuration defining all working/output directory constants, delay settings, and helper functions to ensure directory presence. No hardcoded paths appear inside scripts.

### 2. `harvest.py` (Script 1)
Pulls tournament standings, records, and authentic pairing matchup statistics from the Limitless TCG API (`play.limitlesstcg.com/api`).
- Employs pagination and strict rate-limiting (`0.5s` delay).
- Caches raw metadata and standings to `cache/standings/{id}.txt`. Never re-fetches cached tournaments.
- Writes full flat sequence decklists to `processed/decklists.txt`.
- Computes decisive archetype vs archetype winrates and writes `processed/matchup_matrix.txt`.

### 3. `enrich.py` (Script 2)
Fetches and classifies card data from `api.pokemontcg.io` with robust retry and rate-limiting logic. Reads `POKEMONTCG_API_KEY` from the environment if present.
- **Supertype Classification:** Strict parsing for Trainers and Energies.
- **Pokémon Role Classification:**
  - *Deck Name & Evolution:* Extracts Pokémon from deck archetype names and recursively walks `evolvesFrom` and `evolvesTo` metrics to classify definitive main attackers (`main_pokemon`).
  - *Modifier Extraction:* Parses card names for affiliations (e.g. `"Team Rocket's"`, `"N's"`) and scans subtypes/rules for special tags (`ex`, `rule_box`, `ancient`, etc.).
  - *BoW Feature Vector:* Tokenizes abilities, attacks, damage output, and retreat costs. Subtracts damage keyword hits from weighted Support Ability keyword hits to classify functional support units (`support_pokemon`) vs attackers.
  - *Anti-Meta Signal:* Measures card appearance deltas inside victorious archetypes vs global baselines to highlight strategic tech options.
- Writes the master dictionary literal declaration to `processed/cards_enriched.py`.

### 4. `cooccurrence.py` (Script 3)
Calculates weighted co-occurrence contribution scores for all distinct card pairs appearing within the same decklists:
$$\text{contribution} = \left(\frac{1}{\text{placing}}\right) \times \text{placing\_weight}$$
(Where `placing_weight` is `1.0` for Top 4, `0.8` for Top 8, `0.6` for Top 16, and `0.3` for all others). Writes `processed/cooccurrence.txt` sorted descending by score.

### 5. `cluster.py` (Script 4)
Constructs a weighted undirected co-occurrence graph using `networkx` and detects functional communities via `python-louvain` community detection.
- Filters clusters to contain between `2` and `6` cards with minimum average internal edge weights $\ge 50$.
- Separates universal staples (>85% ubiquity) into `processed/clusters_staples.txt` to keep pure functional relationships in `processed/clusters.txt`.

### 6. `write_db.py` (Script 5)
Compiles all data into the human-readable flat-file deliverable database in `db/`.
- **Merge & Backup Protection:** Automatically creates timestamped archives in `backups/` and reads existing output files to preserve manual curations (`properties`, `label`, `notes`) instead of resetting them.
- **Parsing Constraints:** Strictly enforces split limits (`line.split(":-", 1)`) and formatted list pipe delimiters (`card_name|weight`) for robust downstream parsing.

### 7. `run_pipeline.py` (Script 6)
Master orchestration entry point executing all pipeline steps in sequence with authentic timestamp logs.
- Supports `--skip-harvest` flag to skip new tournament downloads and run NLP BoW/clustering on cached files.
- Supports `--from {script_name}` to resume execution from any specific phase.
- Supports `--keep-intermediate` to retain active working state in `cache/` and `processed/` (which are cleanly wiped by default upon full execution).

---

## Execution Instructions

To run the complete batch pipeline from scratch:
```bash
python3 run_pipeline.py
```

To resume from Bag-of-Words feature vector enrichment without harvesting new tournament lists:
```bash
python3 run_pipeline.py --skip-harvest --keep-intermediate
```

To run individual scripts standalone:
```bash
python3 harvest.py
python3 enrich.py
python3 cooccurrence.py
python3 cluster.py
python3 write_db.py
```
