#!/usr/bin/env python3

import argparse
import sys
import os
import shutil
import subprocess
from pathlib import Path
import xml.etree.ElementTree as xml


DEBUG=False

class AssetPorter:
    def __init__(
            self, # AssetPorter, python does not support forward references -.-
            src_root: Path,
            dst_root: Path,
            tmp_dir: Path,
            out_dir: Path,
            packtools_dir: Path):
        self.src_root = src_root
        self.dst_root = dst_root
        self.tmp_dir = tmp_dir
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir = out_dir
        self.packtools_dir = packtools_dir

    def port(self, asset: str):
        asset_file = asset + '.pkg'

        if os.path.exists(self.out_dir/asset_file):
               # asset already exists in the destination game
               print(f"skipping {asset} because it already exists in out dir")
               return

        src_asset_path = self.src_root/'data'/'asset'/'D3D11'/asset_file
        if not os.path.exists(src_asset_path):
            # If we cannot find it in data/assets/D3D11, check in D3D11_us
            src_asset_path =  src_asset_path.parent.parent /'D3D11_us' / asset_file
        src_asset_tmp_path = self.tmp_dir/'src'/asset_file
        src_asset_tmp_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src_asset_path, src_asset_tmp_path)

        print(f"Unpacking {asset_file}...")
        try:
            unpacker = self.packtools_dir/'ed8pkg2gltf.py'
            subprocess.run(
                ['python', unpacker, '-o', str(src_asset_tmp_path)],
                check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as e:
            print(f"FATAL: Error unpacking package {src_asset_tmp_path}:\nSTDERR:\n{e.stderr}\nSTDOUT:\n{e.stdout}\n", file=sys.stderr)
            sys.exit(1)

        print(f"Replacing shaders and material...")
        try:
            tmp_dst_assets = self.tmp_dir/'dst'
            replacer = self.packtools_dir/'replace_shaders_and_mats_cs1.py'
            subprocess.run([
                    'python',
                    replacer,
                    f'--cs1-root={self.dst_root}',
                    f'--tmp-dir={tmp_dst_assets}',
                    f'--packtools-dir={self.packtools_dir}',
                    str(src_asset_tmp_path.with_suffix(''))],
                check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError as e:
            print(f"FATAL: Error replacing shaders and materials {src_asset_tmp_path}:\nSTDERR:\n{e.stderr}\nSTDOUT:\n{e.stdout}\n", file=sys.stderr)
            sys.exit(1)

        # Does not work on linux right now skip
        if os.path.exists('/proc/self'):
            print(f"Terminating early because packing doesn't work on linux")
            sys.exit(0)

        print(f"Packing asset {src_asset_tmp_path}...")
        # The build_collada.py cannot properly model output path, etc. for now
        # just copy everything over to not have to think about it...
        # We should fix build_collada.py eventually...
        asset_dir = str(src_asset_tmp_path.with_suffix(''))
        for f in self.packtools_dir.glob('[a-z][A-Z]*'):
            if os.path.isdir(f):
                continue
            # For some reason windows does not allow copying byte identical
            # files. So only copy it if it does not yet exist.
            path = Path(asset_dir)/Path(f).name
            if not os.path.exists(path):
                shutil.copy(f, asset_dir)
            else:
                print(f"{path} already exists, skip copying")

        try:
            build_collada = src_asset_tmp_path.with_suffix('')/'build_collada_cs1.py'
            subprocess.run([
                    'python',
                    build_collada,
                    ],
                check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError as e:
            print(f"FATAL: Error re-packing (build_collda_cs1.py) asset {src_asset_tmp_path}:\nSTDERR:\n{e.stderr}\nSTDOUT:\n{e.stdout}\n", file=sys.stderr)
            sys.exit(1)

        try:
            path = src_asset_tmp_path.with_suffix('')/'RunMe.bat'
            # using relative path because we set the cwd.
            subprocess.run([path.resolve()],
                check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=src_asset_tmp_path.with_suffix('')
            )
        except subprocess.CalledProcessError as e:
            print(f"FATAL: Error re-packing (RunMe.bat) asset {src_asset_tmp_path}:\nSTDERR:\n{e.stderr}\nSTDOUT:\n{e.stdout}\n", file=sys.stderr)
            sys.exit(1)

        shutil.copy(src_asset_tmp_path.with_suffix('')/Path(asset+'.pkg'), self.out_dir)
        print(f"finished packing {asset}")

def main():
    parser = argparse.ArgumentParser(
        description="Finds all objects referenced in an cs2 .ops file and ports to them be compatible with cs1.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # --- Argument Definition ---
    # Required arguments. Will prompt user to provide if missing.
    parser.add_argument(
        "--cs1-root",
        type=Path,
        help="Required: Root directory for cs1 steam game (e.g., 'Steam/steamapps/common/Trails of Cold Steel')."
    )
    parser.add_argument(
        "--cs2-root",
        type=Path,
        help="Required: Root directory for cs2 steam game (e.g., 'Steam/steamapps/common/Trails of Cold Steel II')."
    )
    # Arguments with default values
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("."),
        help="Path where to store the output .pkg files."
    )
    parser.add_argument(
        "--tmp-dir",
        type=Path,
        default=Path("tmp"),
        help="Path to the temporary working directory."
    )
    parser.add_argument(
        "--packtools-dir",
        type=Path,
        default=Path("."),
        help="Path to the directory containing the (un)pack tools from https://github.com/eArmada8/ed8pkg2gltf (including the find_similar_shaders.py and all_shaders.csv) and the shader replace tool from https://github.com/bernd7055/tools/blob/main/replace_shaders_and_mats_cs1.py."
    )
    parser.add_argument(
            'ops_files',
            nargs='*',
            metavar='tXXXX.ops',
            type=Path,
            help="Name(s) of .ops file(s) to port to cs1 (ports all .ops files in the current directory if not provided.)."
    )

    args = parser.parse_args()

    # --- Configuration from Arguments ---
    CS1_ROOT = args.cs1_root
    while not CS1_ROOT or not os.path.exists(CS1_ROOT):
        CS1_ROOT = Path(input("Please enter the path to your CS1 installation (e.g. 'C:\\Program Files (x86)\\Steam\\steamapps\\common\\Trails of Cold Steel': "))
    CS2_ROOT = args.cs2_root
    while not CS2_ROOT or not os.path.exists(CS2_ROOT):
        CS2_ROOT = Path(input("Please enter the path to your CS2 installation (e.g. 'C:\\Program Files (x86)\\Steam\\steamapps\\common\\Trails of Cold Steel II': "))
    OUT_DIR = args.out_dir
    TMP_DIR = args.tmp_dir
    OPS_FILES = args.ops_files
    if not OPS_FILES:
        OPS_FILES = list(Path.cwd().glob("*.ops"))
    PACKTOOLS_DIR = args.packtools_dir


    # --- Collect Assets ---
    assets = set()
    for ops_file in OPS_FILES:
        xml_tree = xml.parse(ops_file).getroot()
        mos = xml_tree.findall('MapObjects')
        # Normally there is exactly one MapObjects. This is just a safeguard in
        # in case there are .ops files with multiple map objects.
        assets_objs = [x for mo in mos for x  in mo.findall('AssetObject')]
        assets.update([asset.get('asset') for asset in assets_objs])

    # --- Port Assets ---
    asset_porter = AssetPorter(
            src_root = CS2_ROOT,
            dst_root = CS1_ROOT,
            tmp_dir = TMP_DIR,
            out_dir = OUT_DIR,
            packtools_dir = PACKTOOLS_DIR)

    for asset in assets:
        asset_porter.port(asset)

if __name__ == "__main__":
    main()
