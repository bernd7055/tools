# Usage:
#   python replace_material.py metadata.json shader_map.txt
# where
#   metadata.json is the file in which to replace materials (values only)
#   shader_map.txt is a csv of format shader_name,replace_shader,asset
#       replace_shader is the shader which with the original shader to replace
#       asset is the path to the extracted asset in which a material with the shader can be found

import json, csv, os, argparse, glob

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
    dst["shaderSwitches"] = merge_dicts(dst["shaderSwitches"], src["shaderSwitches"])
    return dst


if __name__ == '__main__':
        parser = argparse.ArgumentParser()
        parser.add_argument('metadata_filename', help="Name of metadata file to process (required).")
        parser.add_argument('shader_map', help="Name of csv file that maps from shader to file where to find donor material for that shader.")
        parser.add_argument('-o', '--outfile', type=str, help="Path where to store the result. prints to stdout otherwise")
        args = parser.parse_args()

        with open(args.metadata_filename, 'rb') as f:
            metadata = json.loads(f.read())
        with open(args.shader_map) as f:
            reader = csv.reader(f, delimiter=',')
            next(reader)
            shader_map = dict((row[0], (row[1],row[2])) for row in reader)
        files_to_shaders_to_materials = {}
        mats = metadata["materials"]
        for (m, v) in mats.items():
            shader = v["shader"].removeprefix("shaders/")
            if shader in shader_map:
                mapping = shader_map[shader]
                replace_shader, file = mapping[0], mapping[1]
                if replace_shader:
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
            for d in glob.glob(donor_asset+"metadata*.json"):
                with open(d, 'rb') as f:
                    donor = json.loads(f.read())
                    donor_mats.update({ v["shader"].removeprefix("shaders/"): v for (k,v) in donor["materials"].items() if v["shader"].removeprefix("shaders/") in stm })
            for (s, ms) in stm.items():
                donor_mat = donor_mats[s]
                for m in ms:
                    mats[m] = merge_mats(mats[m], donor_mat)
        res = json.dumps(metadata, indent=4)
        if args.outfile:
            with open(args.outfile, 'w') as f:
                f.write(res)
        else:
            print(res)
