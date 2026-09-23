#!/bin/bash
# One-command launcher for Aider against the local qwen2.5-coder model via Ollama.
# No API key, no token cost -- runs entirely on this machine.
#
# Usage:
#   tools/aider-local.sh                  # interactive chat
#   tools/aider-local.sh "your prompt"    # one-shot: run a message and exit
#
# Requires: Ollama running (the menu-bar app, or `ollama serve`) with
# qwen2.5-coder:7b pulled (`ollama pull qwen2.5-coder:7b`).

set -e
cd "$(dirname "$0")/.."   # repo root, so .aider.conf.yml is picked up

export PATH="$HOME/.local/bin:$PATH"
export OLLAMA_API_BASE="${OLLAMA_API_BASE:-http://localhost:11434}"

if ! curl -s -o /dev/null "$OLLAMA_API_BASE/api/version"; then
  echo "Ollama doesn't seem to be running at $OLLAMA_API_BASE — start the Ollama app or run 'ollama serve'." >&2
  exit 1
fi

if [ -n "$1" ]; then
  aider --message "$1" --yes-always --no-gitignore
else
  aider --no-gitignore
fi
