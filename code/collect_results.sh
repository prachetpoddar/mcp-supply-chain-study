#!/bin/bash
# Moves your own run outputs from ~/Downloads into results/.
# Safe to run repeatedly; only moves files it finds.
DEST="$HOME/Documents/MCPSupplyChainStudy/results"
mkdir -p "$DEST"
for f in pypi_weighted_result.json mcp_docker.json conc_docker.json \
         conc_smithery.json conc_npm.json mcp_smithery.json \
         mcp_registry.json mcp_npm_downloads.json npm_downloads.json; do
  [ -f "$HOME/Downloads/$f" ] && mv "$HOME/Downloads/$f" "$DEST/" && echo "  moved $f"
done
echo "results/ now holds:"; ls -1 "$DEST" 2>/dev/null | sed 's/^/  /'
