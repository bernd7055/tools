#!/bin/sh
set -eu pipefail
CS1ROOT=~/cs1
mkdir -p tmp/exact_shaders
mkdir -p tmp/close_shaders
MAPNAME=$(basename "$(pwd)")
MAPPING=tmp/shader_mapping.csv
echo 'orig,closest,asset' > ${MAPPING}
for i in ${MAPNAME}/ed8.fx#*.phyre; do
    shadername=`basename $i`;
    basename="${shadername%.*}"
    cs1pkg=`(awk --csv "/${basename}/ {print \\$2}" all_shaders.csv)`
    DEST=tmp/exact_shaders
    closest_shader=""
    if [[ "$cs1pkg" == "None" ]]; then
        closest_shader=`(python find_similar_shaders.py -s="${basename}" -g=cs1 -p=True)`
        DEST=tmp/close_shaders
        cs1pkg=`(awk --csv "/${closest_shader}/ {print \\$2}" all_shaders.csv)`
        shadername=${closest_shader}.phyre
#        echo best effort for ${basename}: using $closest_shader
    fi
    if [[ ! -f tmp/${cs1pkg} ]]; then
        if [[ -f ${CS1ROOT}/data/asset/D3D11/${cs1pkg} ]]; then
            cp ${CS1ROOT}/data/asset/D3D11/${cs1pkg} tmp
        elif [[ -f ${CS1ROOT}/data/asset/D3D11_us/${cs1pkg} ]]; then
            cp ${CS1ROOT}/data/asset/D3D11_us/${cs1pkg} tmp
        else
            echo cannot find ${cs1pkg}
        fi
    fi
    pkgbname="${cs1pkg%.pkg}"
    echo ${basename},${closest_shader},tmp/${pkgbname}/ >> ${MAPPING}
    if [[ ! -d tmp/${pkgbname} ]]; then
        python ed8pkg2gltf.py tmp/${cs1pkg}
    fi
    cp tmp/${pkgbname}/${pkgbname}/${shadername} ${DEST}
done

cp tmp/exact_shaders/* ${MAPNAME}/
