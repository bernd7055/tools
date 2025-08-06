#!/usr/bin/env python3

import sys
import shutil
import csv
import subprocess
import argparse
from pathlib import Path

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

    args = parser.parse_args()

    # --- Configuration from Arguments ---
    CS1_ROOT = args.cs1_root
    MAP_NAME = args.map_name
    ALL_SHADERS_CSV = args.shaders_csv
    TMP_DIR = args.tmp_dir

    # Derived, non-configurable paths
    DEST_DIR = TMP_DIR / "exact_shaders"
    MAPPING_CSV = TMP_DIR / "shader_mapping.csv"

    # --- Pre-run Setup ---
    shader_db = load_shader_database(ALL_SHADERS_CSV)
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    map_dir = Path(MAP_NAME)
    if not map_dir.is_dir():
        print(f"FATAL: Map directory '{map_dir}' not found.", file=sys.stderr)
        sys.exit(1)

    # --- Main Processing Loop ---
    with open(MAPPING_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['orig', 'closest', 'asset'])

        glob_pattern = f"{MAP_NAME}/ed8.fx#*.phyre"
        shader_files = list(Path.cwd().glob(glob_pattern))
        print(f"Found {len(shader_files)} shaders to process in '{map_dir}'.")

        for shader_path in shader_files:
            base_name = shader_path.stem
            print(f"--- Processing {base_name} ---")

            cs1_pkg = shader_db.get(base_name)
            closest_shader, shader_name_with_ext = base_name, shader_path.name

            if not cs1_pkg:
                print(f"Shader '{base_name}' not in database. Finding a similar one...")
                try:
                    result = subprocess.run(
                        ['python', 'find_similar_shaders.py', f'-s={base_name}', '-g=cs1', '-p=True'],
                        capture_output=True, text=True, check=True, encoding='utf-8'
                    )
                    closest_shader = result.stdout.strip()
                    cs1_pkg = shader_db.get(closest_shader)
                    shader_name_with_ext = f"{closest_shader}.phyre"
                except (subprocess.CalledProcessError, FileNotFoundError) as e:
                    print(f"FATAL: Error finding similar shader for {base_name}: {e}", file=sys.stderr)
                    sys.exit(1)

            if not cs1_pkg:
                print(f"FATAL: Could not find a package for '{base_name}' or alternative '{closest_shader}'.", file=sys.stderr)
                sys.exit(1)

            pkg_path_in_tmp = TMP_DIR / cs1_pkg
            pkg_base_name = Path(cs1_pkg).stem
            unpacked_pkg_dir = TMP_DIR / pkg_base_name

            if not pkg_path_in_tmp.is_file():
                source_pkg_path = find_cs1_asset_path(cs1_pkg, CS1_ROOT)
                if source_pkg_path:
                    shutil.copy(source_pkg_path, TMP_DIR)
                else:
                    print(f"FATAL: Cannot find source package '{cs1_pkg}'.", file=sys.stderr)
                    sys.exit(1)

            asset_path_for_csv = f"tmp/{pkg_base_name}/"
            writer.writerow([base_name, closest_shader, asset_path_for_csv])

            if not unpacked_pkg_dir.is_dir():
                print(f"Unpacking {pkg_path_in_tmp}...")
                try:
                    subprocess.run(
                        ['python', 'ed8pkg2gltf.py', str(pkg_path_in_tmp)],
                        check=True, capture_output=True, text=True
                    )
                except subprocess.CalledProcessError as e:
                    print(f"FATAL: Error unpacking package {pkg_path_in_tmp}:\n{e.stderr}", file=sys.stderr)
                    sys.exit(1)

            final_shader_source = unpacked_pkg_dir / pkg_base_name / shader_name_with_ext
            if final_shader_source.is_file():
                shutil.copy(final_shader_source, DEST_DIR)
            else:
                print(f"FATAL: Final shader '{shader_name_with_ext}' not found in unpacked package.", file=sys.stderr)
                sys.exit(1)

    # --- Final Step ---
    print(f"Copying all found shaders from {DEST_DIR} to {map_dir}/")
    for found_shader in DEST_DIR.glob('*'):
        if found_shader.is_file():
            shutil.copy(found_shader, map_dir)
            print(f"  -> Copied {found_shader.name}")

if __name__ == "__main__":
    main()
