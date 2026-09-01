#!/usr/bin/env bash

nii_dir=$(realpath "$1")
stl_dir=$(realpath "$2")
profile="$3"
if [[ $# -lt 2 ]]; then
    echo "Usage: batch_jig.sh <nii_input_dir> <stl_output_dir>" >&2
    exit 1
fi
if [[ ! -d "$nii_dir" || -z $(ls -A "${nii_dir}"/*.nii*) ]]; then
    echo "Directory "$nii_dir" does not exist or contains no NIfTI files" >&2
    exit 1
fi
if [[ ! -d "$stl_dir" ]]; then
    mkdir "$stl_dir"
fi

cd "$(dirname "${BASH_SOURCE[0]}")"
for n in "$nii_dir"/*.nii* ; do
    filename="${n##*/}"
    stl_path="${stl_dir}/${filename%%.*}.stl"
    [[ -z "$profile" ]] && profile="${filename%%_*}"
    hatch run python autojigger.py -i "$n" -o "$stl_path" -p "$profile" &
done
wait