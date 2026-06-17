import os
import sys
import shutil
import argparse
import subprocess
from datetime import datetime
import config

def log(msg):
    t_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{t_str}] {msg}", flush=True)

SCRIPTS = [
    ("harvest", "harvest.py", "Starting harvest...", "Harvest complete."),
    ("enrich", "enrich.py", "Starting enrichment...", "Enrichment complete."),
    ("cooccurrence", "cooccurrence.py", "Starting co-occurrence scoring...", "Co-occurrence complete."),
    ("cluster", "cluster.py", "Starting clustering...", "Clustering complete."),
    ("write_db", "write_db.py", "Starting database writing...", "Database writing complete.")
]

def main():
    parser = argparse.ArgumentParser(description="Pokémon TCG Data Harvester & BoW Pipeline")
    parser.add_argument("--skip-harvest", action="store_true", help="Skip Script 1 (harvest) and use existing cached/processed data")
    parser.add_argument("--from", dest="from_script", help="Resume from a specific script (e.g. enrich, cooccurrence, cluster, write_db)")
    parser.add_argument("--keep-intermediate", action="store_true", help="Do not delete cache/ and processed/ directories at the end of execution")
    args = parser.parse_args()

    start_idx = 0
    if args.skip_harvest:
        start_idx = 1

    if args.from_script:
        clean_name = args.from_script.lower().replace(".py", "")
        script_keys = [s[0] for s in SCRIPTS]
        if clean_name in script_keys:
            start_idx = script_keys.index(clean_name)
        else:
            log(f"Error: Unknown script name for --from: '{args.from_script}'. Valid options: {script_keys}")
            sys.exit(1)

    log("Initializing Pipeline Execution...")

    for key, script_file, start_msg, end_msg in SCRIPTS[start_idx:]:
        log(start_msg)
        script_path = os.path.join(os.path.dirname(__file__) if os.path.dirname(__file__) else ".", script_file)
        
        if not os.path.exists(script_path):
            log(f"Error: Required script {script_file} not found at {script_path}")
            sys.exit(1)

        ret = subprocess.run([sys.executable, script_path])
        if ret.returncode != 0:
            log(f"Pipeline execution failed during {script_file} with exit code {ret.returncode}")
            sys.exit(ret.returncode)
            
        log(end_msg)

    log("Pipeline complete. DB written to db/")

    # Clean up intermediate working state unless requested otherwise
    if not args.keep_intermediate:
        log("Cleaning up intermediate working state (cache/ and processed/)...")
        if os.path.exists(config.CACHE_DIR):
            shutil.rmtree(config.CACHE_DIR, ignore_errors=True)
        if os.path.exists(config.PROCESSED_DIR):
            shutil.rmtree(config.PROCESSED_DIR, ignore_errors=True)
        log("Cleanup complete.")
    else:
        log("Retaining intermediate working directories due to --keep-intermediate flag.")

if __name__ == "__main__":
    main()
