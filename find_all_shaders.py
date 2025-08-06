#!/usr/bin/env python3

import sys
import shutil
import csv
import subprocess
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Set

# --- Helper Functions ---

def load_shader_database(csv_path: Path) -> dict[str, str]:
    """
    Parses the shader CSV file once and loads it into a dictionary for fast lookups.
    The dictionary maps a shader's base name to its package name.
    """
    database = {}
    try:
        with open(csv_path, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader, None)  # Skip header
            for row in reader:
                if len(row) > 1:
                    shader_name, package_name = row[0], row[1]
                    # Store only if the package is valid (not empty or "None")
                    if package_name and package_name != "None":
                        database[shader_name] = package_name
    except FileNotFoundError:
        print(f"FATAL: Database file '{csv_path}' not found.", file=sys.stderr)
        sys.exit(1)
    return database

def find_cs1_asset_path(pkg_name: str, cs1_root: Path) -> Path | None:
    """Searches for the asset package in predefined standard directories."""
    path_d3d11 = cs1_root / "data/asset/D3D11" / pkg_name
    if path_d3d11.is_file():
        return path_d3d11

    path_d3d11_us = cs1_root / "data/asset/D3D11_us" / pkg_name
    if path_d3d11_us.is_file():
        return path_d3d11_us

    return None

def unpack_package(pkg_path_in_tmp: Path) -> None:
    """Unpacks a single asset package using the ed8pkg2gltf script."""
    print(f"Unpacking {pkg_path_in_tmp}...")
    try:
        subprocess.run(
            ['python', 'ed8pkg2gltf.py', str(pkg_path_in_tmp)],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"FATAL: Error unpacking package {pkg_path_in_tmp}:\n{e.stderr}", file=sys.stderr)
        sys.exit(1)

# --- Main Script Logic ---

def main():
    """Main function to orchestrate the shader processing workflow."""
    parser = argparse.ArgumentParser(
        description="Replaces all shaders with appropriate cs1 shaders and records which shaders were used as replacement.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # --- Argument Definition ---
    # Required arguments
    parser.add_argument(
        "--cs1-root",
        type=Path,
        required=True,
        help="Required: Root directory for cs1 steam game (e.g., 'Steam/steamapps/common/Trails of Cold Steel')."
    )
    parser.add_argument(
        "--map-name",
        type=str,
        required=True,
        help="Required: The directory containing the shader files that should be replaces (e.g., 'M_T4040' after extracing with 'python ed8pkg2gltf M_T4040.pkg')."
    )
    # Arguments with default values
    parser.add_argument(
        "--shaders-csv",
        type=Path,
        default=Path("all_shaders.csv"),
        help="Path to the CSV file containing all known shaders."
    )
    parser.add_argument(
        "--tmp-dir",
        type=Path,
        default=Path("tmp"),
        help="Path to the temporary working directory."
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=16,
        help="Maximum number of parallel workers for unpacking assets."
    )

    args = parser.parse_args()

    # --- Configuration from Arguments ---
    CS1_ROOT = args.cs1_root
    MAP_NAME = args.map_name
    ALL_SHADERS_CSV = args.shaders_csv
    TMP_DIR = args.tmp_dir
    MAX_WORKERS = args.max_workers

    # Derived, non-configurable paths
    MAPPING_CSV = TMP_DIR / "shader_mapping.csv"

    # --- Pre-run Setup ---
    shader_db = load_shader_database(ALL_SHADERS_CSV)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    map_dir = Path(MAP_NAME)
    if not map_dir.is_dir():
        print(f"FATAL: Map directory '{map_dir}' not found.", file=sys.stderr)
        sys.exit(1)

    # --- Phase 1: Determine which assets to unpack and which shaders to copy ---
    print("\n--- Phase 1: Computing asset requirements ---")

    shaders_to_process = list(Path.cwd().glob(f"{MAP_NAME}/ed8.fx#*.phyre"))
    print(f"Found {len(shaders_to_process)} shaders to process in '{map_dir}'.")

    packages_to_unpack: Set[Path] = set()
    shader_mapping: List[Tuple[str, str, str]] = []

    for shader_path in shaders_to_process:
        base_name = shader_path.stem
        closest_shader = base_name

        # Check if the shader is in the database
        cs1_pkg = shader_db.get(base_name)

        # If not, find a similar one
        if not cs1_pkg:
            print(f"Shader '{base_name}' not in database. Finding a similar one...")
            try:
                result = subprocess.run(
                    ['python', 'find_similar_shaders.py', f'-s={base_name}', '-g=cs1', '-p=True'],
                    capture_output=True, text=True, check=True, encoding='utf-8'
                )
                closest_shader = result.stdout.strip()
                cs1_pkg = shader_db.get(closest_shader)
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                print(f"FATAL: Error finding similar shader for {base_name}: {e}", file=sys.stderr)
                sys.exit(1)

        if not cs1_pkg:
            print(f"FATAL: Could not find a package for '{base_name}' or alternative '{closest_shader}'.", file=sys.stderr)
            sys.exit(1)

        # Record the mapping and the package to be unpacked
        pkg_base_name = Path(cs1_pkg).stem
        packages_to_unpack.add(Path(cs1_pkg))
        asset_path_for_csv = f"tmp/{pkg_base_name}/"
        shader_mapping.append((base_name, closest_shader, asset_path_for_csv))

    print(f"Identified {len(packages_to_unpack)} unique packages to unpack.")

    # --- Phase 2: Unpack assets in parallel ---
    print("\n--- Phase 2: Unpacking assets in parallel ---")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Copy necessary packages to the temporary directory
        futures = []
        for cs1_pkg in packages_to_unpack:
            pkg_path_in_tmp = TMP_DIR / cs1_pkg
            if not pkg_path_in_tmp.is_file():
                source_pkg_path = find_cs1_asset_path(cs1_pkg, CS1_ROOT)
                if source_pkg_path:
                    shutil.copy(source_pkg_path, TMP_DIR)
                else:
                    print(f"FATAL: Cannot find source package '{cs1_pkg}'.", file=sys.stderr)
                    sys.exit(1)
            # Submit the unpacking task to the thread pool
            futures.append(executor.submit(unpack_package, pkg_path_in_tmp))

        # Wait for all unpacking tasks to complete
        for future in as_completed(futures):
            future.result()  # This will re-raise any exceptions from the worker threads

    print("All packages unpacked successfully.")

    # --- Phase 3: Copy all shaders and write the mapping file (single-threaded) ---
    print("\n--- Phase 3: Copying shaders and writing mapping file ---")

    with open(MAPPING_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['orig', 'closest', 'asset'])

        for orig_shader, closest_shader, asset_path_for_csv in shader_mapping:
            writer.writerow([orig_shader, closest_shader, asset_path_for_csv])

            pkg_base_name = Path(asset_path_for_csv.replace('tmp/', '')).stem
            unpacked_pkg_dir = TMP_DIR / pkg_base_name
            shader_name_with_ext = f"{closest_shader}.phyre"

            final_shader_source = unpacked_pkg_dir / pkg_base_name / shader_name_with_ext
            if final_shader_source.is_file():
                shutil.copy(final_shader_source, map_dir)
                print(f" -> Copied {final_shader_source.name} to {map_dir}")
            else:
                print(f"FATAL: Final shader '{shader_name_with_ext}' not found in unpacked package '{unpacked_pkg_dir}'.", file=sys.stderr)
                sys.exit(1)

if __name__ == "__main__":
    main()
