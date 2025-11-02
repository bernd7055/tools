#!/usr/bin/env python3

import argparse
import sys
import os
import shutil
import subprocess
from pathlib import Path
import xml.etree.ElementTree as xml


DEBUG=False

class Logger:
    def __init__(self):
        self.log_lines = []

    def log(self, msg):
        print(msg, file=sys.stderr)
        self.log_lines.append(msg)

    def get_log(self):
        return '\n'.join(self.log_lines)


class AssetPorter:
    def __init__(
            self, # AssetPorter, python does not support forward references -.-
            src_root: Path,
            dst_root: Path,
            tmp_dir: Path,
            out_dir: Path,
            packtools_dir: Path,
            flip_textures_vertically: bool,
            ):
        self.src_root = src_root
        self.dst_root = dst_root
        self.tmp_dir = tmp_dir
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir = out_dir
        self.packtools_dir = packtools_dir

    def port(self, asset: str) -> Logger | None:
        logger = Logger()
        asset_file = asset + '.pkg'

        if os.path.exists(self.out_dir/asset_file):
               # asset already exists in the destination game
               print(f"skipping {asset} because it already exists in out dir", file=sys.stderr)
               return

        src_asset_path = self.src_root/'data'/'asset'/'D3D11'/asset_file
        if not os.path.exists(src_asset_path):
            # If we cannot find it in data/assets/D3D11, check in D3D11_us
            src_asset_path =  src_asset_path.parent.parent /'D3D11_us' / asset_file
        src_asset_tmp_path = self.tmp_dir/'src'/asset_file
        src_asset_tmp_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src_asset_path, src_asset_tmp_path)

        logger.log(f"Unpacking {asset_file}...")
        try:
            unpacker = self.packtools_dir/'ed8pkg2gltf.py'
            subprocess.run(
                ['python', unpacker, '-o', str(src_asset_tmp_path)],
                check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as e:
            logger.log(f"FATAL: Error unpacking package {src_asset_tmp_path}:\nSTDERR:\n{e.stderr}\nSTDOUT:\n{e.stdout}\n")
            return logger

        logger.log(f"Replacing shaders and material...")
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
            logger.log(f"FATAL: Error replacing shaders and materials {src_asset_tmp_path}:\nSTDERR:\n{e.stderr}\nSTDOUT:\n{e.stdout}\n")
            return logger

        # The rest of the script does not work on linux right now skip
        if os.path.exists('/proc/self'):
            print(f"Skip packing because packing doesn't work on linux", file=sys.stderr)
            return

        texconv_path = self.packtools_dir/'texconv.exe'
        asset_dir = Path(src_asset_tmp_path.with_suffix(''))
        logger.log(f"Flipping texture vertically in {asset_dir}...")
        for texture in asset_dir.glob('**/*.dds'):
            try:
                tmp_dst_assets = self.tmp_dir/'dst'
                replacer = self.packtools_dir/'replace_shaders_and_mats_cs1.py'
                subprocess.run([
                        texconv_path,
                        '-vflip',
                        '-o', os.path.dirname(texture),
                        '-y',
                        texture],
                    check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL
                )
            except subprocess.CalledProcessError as e:
                logger.log(f"FATAL: Error flipping texture {texture}:\nSTDERR:\n{e.stderr}\nSTDOUT:\n{e.stdout}\n")
                return logger



        logger.log(f"Packing asset {src_asset_tmp_path}...")
        # The build_collada.py cannot properly model output path, etc. for now
        # just copy over everything we need.
        # We should fix build_collada.py eventually...
        needed_pack_tools = [
                'replace_shader_references.py',
                'lib_fmtibvb.py',
                'build_collada_cs1.py',
                'build_collada.py',
                'write_pkg.py',
                'sentools.exe',
                'PhyreAssetProcessor.exe',
                'PhyreAssetDatabase.dll',
                'PhyreAssetDatabaseUnmanaged.dll',
                'PhyreAssetProcessor.dll',
                'PhyreAssetScript.lua',
                'PhyreAssetServices.dll',
                'PhyreAssetSpec.xml',
                'PhyreDummyShaderCreator.exe',
                'PhyreTools.Core.dll',
        ]
        for f in needed_pack_tools:
            src = self.packtools_dir/f
            if not os.path.exists(src):
                # Not logging like the other errors because this is a user
                # error that needs action from the user.
                print(f"packtool '{f}' missing. Cannot proceed. Please add '{f}' to '{self.packtools_dir}'.", file=sys.stderr)
                sys.exit(1)
            # For some reason windows does not allow copying byte identical
            # files. So only copy it if it does not yet exist.
            dst = Path(asset_dir)/Path(src).name
            if not os.path.exists(dst):
                shutil.copy(src, asset_dir)
            else:
                logger.log(f"{dst} already exists, skip copying")

        try:
            build_collada = src_asset_tmp_path.with_suffix('')/'build_collada_cs1.py'
            subprocess.run([
                    'python',
                    build_collada,
                    ],
                check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError as e:
            logger.log(f"FATAL: Error re-packing (build_collda_cs1.py) asset {src_asset_tmp_path}:\nSTDERR:\n{e.stderr}\nSTDOUT:\n{e.stdout}\n")
            return logger

        try:
            path = src_asset_tmp_path.with_suffix('')/'RunMe.bat'
            # using relative path because we set the cwd.
            subprocess.run([path.resolve()],
                check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=src_asset_tmp_path.with_suffix('')
            )
        except subprocess.CalledProcessError as e:
            logger.log(f"FATAL: Error re-packing (RunMe.bat) asset {src_asset_tmp_path}:\nSTDERR:\n{e.stderr}\nSTDOUT:\n{e.stdout}\n")
            return logger

        shutil.copy(src_asset_tmp_path.with_suffix('')/Path(asset+'.pkg'), self.out_dir)
        logger.log(f"finished packing {asset}")
        return None

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
        help="Path to the directory containing the (un)pack tools from https://github.com/eArmada8/ed8pkg2gltf (including the find_similar_shaders.py, all_shaders.csv and the texture converter tool) and the shader replace tool from https://github.com/bernd7055/tools/blob/main/replace_shaders_and_mats_cs1.py."
    )
    parser.add_argument(
        '--texture-flipping',
        dest='flip_textures_vertically',
        action=argparse.BooleanOptionalAction,
        default=True,
        help='Flip all textures vertically before repacking the assets.'
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
            packtools_dir = PACKTOOLS_DIR,
            flip_textures_vertically = args.flip_textures_vertically)

    error_log = ""
    for asset in assets:
        logger = asset_porter.port(asset)
        if logger is not None:
            error_log += f'Failed porting asset {asset}:\n' + logger.get_log() + '\n'

    if error_log != "":
        with open('errors.txt', 'w') as f:
            f.write(error_log)
        print('WARNING: encountered errors while porting assets. This might be a bug in this script or the underlying packtools. Find all errors in errors.txt')
        input("Press Enter to continue.")


if __name__ == "__main__":
    main()
