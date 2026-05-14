#!/bin/bash
# .claude/hooks/post-python-edit.sh
# Runs after any .py file is created or edited

FILE="$TOOL_INPUT_FILE_PATH"

# Only trigger on Python files in app/ or tests/
if [[ "$FILE" == *.py ]] && [[ "$FILE" == app/* || "$FILE" == tests/* ]]; then
  echo "Running tests..."
  cd /Users/jorgemarcos/Desktop/main_directory/projects/sanctioner-app
  uv run pytest tests/ -x -q 2>&1 | tail -20
fi