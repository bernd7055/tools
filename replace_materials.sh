#!/bin/sh
set -eu

MATERIALS=$1
SRC=../../M_T4040_somewhat_working/metadata.json
DST=meta.json
BASE=$(cat ${DST})


# rewrite this so that you don't have to parse the json over and over again
# I probably don't want to do this in pure bash
while IFS= read mat; do
    BASE=$(jq -r --indent 4 ".materials.${mat} = $(jq -r .materials.${mat} ${SRC})" <<<"${BASE}")
done <${MATERIALS}

echo "${BASE}" > ${DST}.new

exit

jq '.materials' metadata.json |  jq '[ first(to_entries[] | select(.value.shader == "shaders/ed8.fx#9C1387E5FCEBBE72147D55B1EFEB7679")) ] | from_entries'
