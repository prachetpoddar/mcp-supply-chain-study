#!/bin/bash
# Creates ~/Documents/MCPSupplyChainStudy and files everything into it.
# Run from wherever you downloaded the study files (probably ~/Downloads).
#   bash setup_folder.sh
set -e
DEST="$HOME/Documents/MCPSupplyChainStudy"
mkdir -p "$DEST"/{paper,data,code,results}

move() { [ -f "$1" ] && mv "$1" "$2/" && echo "  $1"; }

echo "paper/"
move README.md                      "$DEST"
move mcp-supply-chain-nulls.md      "$DEST/paper"

echo "data/"
for f in mcp-study-data.json mcp-study-v2-data.json mcp-controls-data.json \
         mcp-confound-tests.json mcp-variance-dimensions.json \
         mcp-substitutability.json npm_frame_wide_6540.json \
         pypi_sample_for_weighting.json docker_mcp_names.json \
         mcp-config.cdx.json fixture.mcp.json; do
  move "$f" "$DEST/data"
done

echo "code/"
for f in mcplib.py mcp_resolve.py mcp_study.py mcp_study_v2_runners.py \
         mcp_controls.py mcp_confound_tests.py mcp_variance_study.py \
         enumerate_mcp.py docker_pulls.py RUN_A_pypi_weighting.py \
         usage_weighting.py; do
  move "$f" "$DEST/code"
done

echo "results/  (your own run outputs)"
for f in pypi_weighted_result.json npm_downloads.json mcp_docker.json \
         conc_docker.json conc_smithery.json conc_npm.json \
         mcp_smithery.json mcp_registry.json mcp_npm_downloads.json; do
  move "$f" "$DEST/results"
done

echo
echo "done -> $DEST"
find "$DEST" -type f | sed "s|$HOME|~|" | sort
echo
echo "next:  cd $DEST/code && python3 docker_pulls.py ../data/docker_mcp_names.json"
