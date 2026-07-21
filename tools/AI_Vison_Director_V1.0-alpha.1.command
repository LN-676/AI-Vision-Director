#!/bin/zsh
set -e

PROJECT_DIR="/Users/linen/Documents/AI-Vision-Director"
LOG_FILE="/tmp/ai-vison-director-v1.0-alpha.1-launch.log"

cd "$PROJECT_DIR"

echo "Starting AI_Vison_Director V1.0-alpha.1..." | tee "$LOG_FILE"
echo "Project: $PROJECT_DIR" | tee -a "$LOG_FILE"
echo "Log: $LOG_FILE" | tee -a "$LOG_FILE"

if [[ -x ".venv/bin/AI_Vison_Director" ]]; then
  exec .venv/bin/AI_Vison_Director 2>&1 | tee -a "$LOG_FILE"
fi

if [[ -x ".venv/bin/python" ]]; then
  exec env PYTHONPATH=src .venv/bin/python -m autocamtracker.main 2>&1 | tee -a "$LOG_FILE"
fi

echo "Could not find .venv/bin/AI_Vison_Director or .venv/bin/python." | tee -a "$LOG_FILE"
echo "Please install dependencies first:"
echo "  python -m venv .venv"
echo "  .venv/bin/python -m pip install -r requirements.txt"
echo "  .venv/bin/python -m pip install -e ."
read "?Press Return to close..."
