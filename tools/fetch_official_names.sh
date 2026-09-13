#!/bin/sh
# 下载生成名称翻译表所需的权威数据到 /tmp。
#
# 这些是官方中文译名的来源，tools/gen_names.py 会读取它们：
#   /tmp/pkhex    PKHeX 的 en / zh-Hans 对照文件（官方游戏数据提取，首选）
#   /tmp/pokeapi  PokeAPI 的 zh-hans 名称（补充）
#   /tmp/ps       Pokémon Showdown 的 zh-cn 本地化（补充 G-Max 招式等）
#
# 用法：sh tools/fetch_official_names.sh

set -e

PKHEX_BASE=https://raw.githubusercontent.com/kwsch/PKHeX/master/PKHeX.Core/Resources/text
POKEAPI_BASE=https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv
PS_BASE=https://raw.githubusercontent.com/smogon/pokemon-showdown/master/data/text/zh-cn

mkdir -p /tmp/pkhex /tmp/pokeapi /tmp/ps

echo "PKHeX（官方英中对照）..."
for lang in en zh-Hans; do
    suffix=$lang
    [ "$lang" = "zh-Hans" ] && suffix=zh
    for kind in Species Moves Abilities; do
        curl -sfL -o "/tmp/pkhex/$(echo $kind | tr A-Z a-z)_$suffix.txt" \
            "$PKHEX_BASE/other/$lang/text_${kind}_${lang}.txt"
    done
    curl -sfL -o "/tmp/pkhex/items_$suffix.txt" "$PKHEX_BASE/items/text_Items_${lang}.txt"
done

echo "PokeAPI（zh-hans）..."
for f in pokemon_species_names move_names item_names ability_names; do
    curl -sfL -o "/tmp/pokeapi/$f.csv" "$POKEAPI_BASE/$f.csv"
done

echo "Pokémon Showdown（zh-cn）..."
for f in moves abilities items pokedex; do
    curl -sfL -o "/tmp/ps/$f.ts" "$PS_BASE/$f.ts"
done

echo
echo "完成。现在可以运行: python3 tools/gen_names.py"
