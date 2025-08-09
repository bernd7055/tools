#!/usr/bin/env python3

import argparse
import csv
import glob
import json
import os
import shutil
import sys
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Set

# --- Helper Functions ---

DEBUG=False

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

def find_cs1_asset_path(cs1_root: Path, pkg_name: str) -> Path | None:
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
    if os.path.exists(pkg_path_in_tmp.with_suffix("")):
        if DEBUG:
            print(f"{pkg_path_in_tmp} already unpacked")
        return
    print(f"Unpacking {pkg_path_in_tmp}...")
    try:
        subprocess.run(
            ['python', 'ed8pkg2gltf.py', str(pkg_path_in_tmp)],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"FATAL: Error unpacking package {pkg_path_in_tmp}:\n{e.stderr}", file=sys.stderr)
        sys.exit(1)

def find_appropriate_cs1_shaders(
        shaders: [Path],
        shader_db: dict[str, str],
        TMP_DIR: Path) -> Tuple[Set[Path], List[Tuple[str, str, str]]]:
    packages_to_unpack: Set[Path] = set()
    shader_mapping: List[Tuple[str, str, str]] = []
    for shader_path in shaders:
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
        packages_to_unpack.add(Path(cs1_pkg))
        asset_path_for_csv = TMP_DIR / Path(cs1_pkg).stem
        shader_mapping.append((base_name, closest_shader, asset_path_for_csv))

    return packages_to_unpack, shader_mapping

def replace_materials(
        shader_mapping: Tuple[str,str,str],
        metadata_filepath: Path,
        map_dir: Path):
    with open(metadata_filepath, 'rb') as f:
        metadata = json.loads(f.read())
    shader_map = dict((row[0], (row[1],row[2])) for row in shader_mapping)
    files_to_shaders_to_materials = {}
    mats = metadata["materials"]
    for (m, v) in mats.items():
        shader = v["shader"].removeprefix("shaders/")
        if shader in shader_map:
            mapping = shader_map[shader]
            replace_shader, file = mapping[0], mapping[1]
            if shader != replace_shader:
                shader = replace_shader
                v["shader"] = "shaders/"+shader
                if "vertex_color_shader" in v:
                    v["vertex_color_shader"] = "shaders/"+shader
            if not file in files_to_shaders_to_materials:
                files_to_shaders_to_materials[file]={}
            shader_to_material = files_to_shaders_to_materials[file]
            if not shader in shader_to_material:
                shader_to_material[shader] = []
            shader_to_material[shader].append(m)
    for (donor_asset, stm) in files_to_shaders_to_materials.items():
        donor_mats = {}
        for d in glob.glob(str(donor_asset)+"/metadata*.json"):
            with open(d, 'rb') as f:
                donor = json.loads(f.read())
                donor_mats.update({ v["shader"].removeprefix("shaders/"): v for (k,v) in donor["materials"].items() if v["shader"].removeprefix("shaders/") in stm })
        for (s, ms) in stm.items():
            # Copy the shader.
            shader_source = Path(f"{donor_asset}/{Path(donor_asset).stem}/{s}.phyre")
            if shader_source.is_file():
                shutil.copy(shader_source, map_dir)
                if DEBUG:
                    print(f"Copied {shader_source} to {map_dir}")
            else:
                print(f"FATAL: Final shader '{shader_source}' not found in unpacked package '{donor_asset}'.", file=sys.stderr)
                sys.exit(1)
            # Update the materials.
            donor_mat = donor_mats[s]
            for m in ms:
                mats[m] = merge_mats(mats[m], donor_mat)

    res = json.dumps(metadata, indent=4)
    with open(metadata_filepath, 'w') as f:
        f.write(res)

# merge_dicts merges dic src into dict dst:
#   * keeps values of dst if key exists in both
#   * adds keys and value if key exists only in src
#   * removes keys if key only exists in dst
def merge_dicts(dst, src):
    res = {}
    for (k,v) in src.items():
        if k in dst:
            res[k] = dst[k]
        else:
            res[k] = src[k]
    return res

# merge_mats merges the shaderParameters and shaderSamplerDefs:
#   * keeps values of dst if key exists in both
#   * adds keys and value if key exists only in src
#   * removes keys if key only exists in dst
def merge_mats(dst, src):
    dst["shaderParameters"] = merge_dicts(dst["shaderParameters"], src["shaderParameters"])
    dst["shaderSamplerDefs"] = merge_dicts(dst["shaderSamplerDefs"], src["shaderSamplerDefs"])
    if "shaderSwitches" in dst:
        dst["shaderSwitches"] = merge_dicts(dst["shaderSwitches"], src["shaderSwitches"])
    return dst

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

    # --- Pre-run Setup ---
    shader_db = load_shader_database(ALL_SHADERS_CSV)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    map_dir = Path(MAP_NAME)
    if not map_dir.is_dir():
        print(f"FATAL: Map directory '{map_dir}' not found.", file=sys.stderr)
        sys.exit(1)

    # --- Phase 1: Determine which assets to unpack and which shaders to copy ---
    print("\n--- Phase 1: Computing asset requirements ---")

    shaders = list(Path.cwd().glob(f"{MAP_NAME}/ed8.fx#*.phyre"))
    print(f"Found {len(shaders)} shaders to process in '{map_dir}'.")

    packages_to_unpack, shader_mapping =  find_appropriate_cs1_shaders(shaders, shader_db, TMP_DIR)

    print(f"Identified {len(packages_to_unpack)} unique packages to unpack.")

    # --- Phase 2: Unpack assets in parallel ---
    print("\n--- Phase 2: Unpacking assets in parallel ---")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Copy necessary packages to the temporary directory
        futures = []
        for cs1_pkg in packages_to_unpack:
            pkg_path_in_tmp = TMP_DIR / cs1_pkg
            if not pkg_path_in_tmp.is_file():
                source_pkg_path = find_cs1_asset_path(CS1_ROOT, cs1_pkg)
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

    # The following shader use a differenct naming scheme and
    # are not in the shader database which is why we treat them
    # separately here.
    default_shaders = [
            "ed8.fx",
            "ed8_minimap.fx#47C02C9B2DC49A1EAA38DC726CC42326",
            "ed8_minimap.fx",
    ]
    default_shaders = [d for d in default_shaders if os.path.exists(f"{MAP_NAME}/{d}.phyre")]

    for cs1_pkg in packages_to_unpack:
        base = cs1_pkg.stem
        found = []
        for d in default_shaders:
            path=f"{TMP_DIR}/{base}/{base}/{d}.phyre"
            if os.path.exists(path):
                found.append(d)
                asset_path = TMP_DIR / base
                shader_mapping.append((d, d, asset_path))
        default_shaders = [d for d in default_shaders if d not in found]

    # check if we found all required default shaders
    # if not, extract them from a well known package that contains
    # all of of them
    if len(default_shaders) != 0:
        well_known_asset = "M_C0120.pkg"
        source_pkg_path = find_cs1_asset_path(CS1_ROOT, well_known_asset)
        if source_pkg_path:
            shutil.copy(source_pkg_path, TMP_DIR)
        else:
            print(f"FATAL: Cannot find source package '{cs1_pkg}'.", file=sys.stderr)
            sys.exit(1)
        dest_path = TMP_DIR / well_known_asset
        unpack_package(dest_path)
        for d in defaults:
            shader_mapping.append((d, d, dest_path.with_suffix("")))

    print("All packages unpacked successfully.")

    # --- Phase 3: Copy all shaders and write the mapping file (single-threaded) ---
    print("\n--- Phase 3: Copying shaders and updating metadata file ---")
    # TODO loop over all metadata*.json?
    metadata_path = Path("metadata.json")
    replace_materials(shader_mapping, metadata_path, map_dir)

if __name__ == "__main__":
    main()
