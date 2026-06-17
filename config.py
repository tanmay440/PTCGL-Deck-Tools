import os

# Pipeline working directories
CACHE_DIR = "cache"
CACHE_CARDS_DIR = os.path.join(CACHE_DIR, "cards")
CACHE_TOURNAMENTS_DIR = os.path.join(CACHE_DIR, "tournaments")
CACHE_STANDINGS_DIR = os.path.join(CACHE_DIR, "standings")

PROCESSED_DIR = "processed"
PROCESSED_DECKLISTS = os.path.join(PROCESSED_DIR, "decklists.txt")
PROCESSED_CARDS_ENRICHED = os.path.join(PROCESSED_DIR, "cards_enriched.py")
PROCESSED_COOCCURRENCE = os.path.join(PROCESSED_DIR, "cooccurrence.txt")
PROCESSED_CLUSTERS = os.path.join(PROCESSED_DIR, "clusters.txt")
PROCESSED_CLUSTERS_STAPLES = os.path.join(PROCESSED_DIR, "clusters_staples.txt")
PROCESSED_MATCHUP_MATRIX = os.path.join(PROCESSED_DIR, "matchup_matrix.txt")

# Output database directories
DB_DIR = "db"
DB_MAIN_POKEMON_DIR = os.path.join(DB_DIR, "main_pokemon")
DB_SUPPORT_POKEMON_DIR = os.path.join(DB_DIR, "support_pokemon")
DB_TRAINERS_DIR = os.path.join(DB_DIR, "trainers")
DB_ENERGIES_DIR = os.path.join(DB_DIR, "energies")
DB_CLUSTERS_DIR = os.path.join(DB_DIR, "clusters")

# Backup directory
BACKUPS_DIR = "backups"

# Request settings
API_DELAY = 0.5

def ensure_directories():
    """Ensure all working and output directories exist."""
    dirs = [
        CACHE_DIR, CACHE_CARDS_DIR, CACHE_TOURNAMENTS_DIR, CACHE_STANDINGS_DIR,
        PROCESSED_DIR, DB_DIR, DB_MAIN_POKEMON_DIR, DB_SUPPORT_POKEMON_DIR,
        DB_TRAINERS_DIR, DB_ENERGIES_DIR, DB_CLUSTERS_DIR, BACKUPS_DIR
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
