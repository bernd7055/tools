#!/bin/sh
usage() {
    echo "Usage: $0 shaders.txt"
    echo "This script removes all meshes that use shaders mentioned in the first argument. It must be execute from the root of an directory created by ed8pkg2gltf.py"
    exit 1
}

if [[ $# < 1 ]]; then
    echo expected at least one argument
    usage
fi
SHADERS=$1
if [[ ! -f $SHADERS ]]; then
    echo $SHADERS does not exist!
    exit 1
fi

declare -A materials
pairs=`(awk '
  /: {/ { m = $1 }
  /"shader"/ { print m $2 }
  ' metadata.json | sed 's@"@@g' | sed 's@:shaders/@ @' | tr -d ',')`
while read -r mat shader; do
    materials[$mat]="$shader"
done <<< "$pairs"

#for key in "${!materials[@]}"; do
#    echo "Key: \"$key\" Value: ${materials[$key]}"
#done

declare -A shaders

while IFS= read i; do
    shader="${i%.phyre}"
    shaders[$shader]=1
done <${SHADERS}

cnt=0
cntr=0
for m in meshes/*.material; do
    cnt=$(($cnt + 1))
    mat=`awk '/material/ {print $2}' $m | sed 's@"@@g'`
    if [[ ! -v materials[$mat] ]]; then
        echo "could not find material \"$mat\""
        exit 1
    fi
    shader=${materials[$mat]}
    if [[ -v shaders[$shader] ]]; then
        echo $mat >> tmp/removed_mats.txt
        cntr=$(($cntr + 1))
        mesh=${m%.material}
        rm $mesh*
    fi
done

echo $cnt
echo $cntr
