#!/usr/bin/env bash

# Build a signature string from key=value input.
# Usage:
#   signature.sh output_format=markdown full_name="Navn" email="user@example.no" model="GPT-5.3-Codex" editor="VS Code"
# Supported output_format values: markdown, JIRA, GitHub
# JIRA output is returned as an ADF paragraph fragment JSON.
# Use mention=yes if you want JIRA output to use mention syntax (@user).

set -euo pipefail

OUTPUT_FORMAT="markdown"
FULL_NAME_INPUT=""
EMAIL_INPUT=""
MODEL="ukjent modell"
EDITOR="ukjent editor"
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
JIRA_USERS_CSV="$SCRIPT_DIR/jira-users.csv"
MENTION=""

function usage() {
  cat <<'EOF'
Usage: signature.sh key=value [key=value ...]

Supported keys:
  output_format=markdown|JIRA|GitHub
  full_name=...
  email=...
  model=...
  editor=...
EOF
}

for arg in "$@"; do
  if [[ "$arg" != *=* ]]; then
    echo "Invalid argument '$arg'. Expected key=value." >&2
    usage >&2
    exit 1
  fi

  key=${arg%%=*}
  value=${arg#*=}

  case "$key" in
    output_format)
      OUTPUT_FORMAT="$value"
      ;;
    full_name)
      FULL_NAME_INPUT="$value"
      ;;
    email)
      EMAIL_INPUT="$value"
      ;;
    model)
      MODEL="$value"
      ;;
    editor)
      EDITOR="$value"
      ;;
    mention)
      MENTION="$value"
      ;;
    *)
      echo "Unknown key '$key'." >&2
      usage >&2
      exit 1
      ;;
  esac
done

case "$OUTPUT_FORMAT" in
  markdown|JIRA|GitHub)
    ;;
  *)
    echo "Invalid output_format '$OUTPUT_FORMAT'." >&2
    usage >&2
    exit 1
    ;;
esac

function full_name_from_git() {
  git config user.name 2>/dev/null || echo ""
}

function email_from_git() {
  git config user.email 2>/dev/null || echo ""
}

function email_from_name() {
  local full_name="$1"
  if [ -z "$full_name" ] || [ ! -f "$JIRA_USERS_CSV" ]; then
    echo ""
    return
  fi

  awk -F, -v full_name="$full_name" 'NR>1 && $2 == full_name {print $1; exit}' "$JIRA_USERS_CSV"
}

function full_name_from_email() {
  local email="$1"
  if [ -z "$email" ] || [ ! -f "$JIRA_USERS_CSV" ]; then
    echo ""
    return
  fi

  awk -F, -v email="$email" 'NR>1 && $1 == email {print $2; exit}' "$JIRA_USERS_CSV"
}

function github_username_from_gh_or_git() {
  local git_config_user
  git_config_user=$(git config --get github.user 2>/dev/null || echo "")
  if [ -n "$git_config_user" ]; then
    echo "$git_config_user"
    return
  fi

  if command -v gh &> /dev/null; then
    local login
    login=$(gh api user --jq .login 2>/dev/null || echo "")
    if [ -n "$login" ]; then
      echo "$login"
      return
    fi

    gh auth status 2>/dev/null | sed -n 's/.*Logged in to github.com account \([^ ]*\).*/\1/p' | head -n 1 || echo ""
  else
    echo ""
  fi
}

function jira_user_id_from_email() {
  local email="$1"
  if [ -z "$email" ] || [ ! -f "$JIRA_USERS_CSV" ]; then
    echo ""
    return
  fi

  # Get Jira user ID from CSV based on email
  local jira_user_id
  jira_user_id=$(awk -F, -v email="$email" 'NR>1 && $1 == email {print $3; exit}' "$JIRA_USERS_CSV")
  echo "$jira_user_id"
}

function jira_user_id_from_name() {
  local full_name="$1"
  if [ -z "$full_name" ] || [ ! -f "$JIRA_USERS_CSV" ]; then
    echo ""
    return
  fi

  awk -F, -v full_name="$full_name" 'NR>1 && $2 == full_name {print $3; exit}' "$JIRA_USERS_CSV"
}

function json_escape() {
  printf '%s' "$1" | tr -d '\r\n\t' | sed 's/\\/\\\\/g; s/"/\\"/g'
}

FULL_NAME="$FULL_NAME_INPUT"
EMAIL="$EMAIL_INPUT"

if [ -n "$EMAIL" ] && [ -z "$FULL_NAME" ]; then
  FULL_NAME=$(full_name_from_email "$EMAIL")
fi

if [ -z "$FULL_NAME" ]; then
  FULL_NAME=$(full_name_from_git)
fi

if [ -z "$EMAIL" ]; then
  EMAIL=$(email_from_name "$FULL_NAME")
fi

if [ -z "$EMAIL" ]; then
  EMAIL=$(email_from_git)
fi

if [ -n "$EMAIL" ] && [ -z "$FULL_NAME" ]; then
  FULL_NAME=$(full_name_from_email "$EMAIL")
fi

GITHUB_USERNAME=$(github_username_from_gh_or_git)
JIRA_USER_ID=""

# Prefer email lookup when available.
if [ -n "$EMAIL" ]; then
  JIRA_USER_ID=$(jira_user_id_from_email "$EMAIL")
fi

if [ -z "$JIRA_USER_ID" ]; then
  JIRA_USER_ID=$(jira_user_id_from_name "$FULL_NAME")
fi

if [ -z "$FULL_NAME" ]; then
  if [ -n "$EMAIL" ]; then
    FULL_NAME="$EMAIL"
  else
    FULL_NAME="ukjent bruker"
  fi
fi

USER_TEXT="$FULL_NAME"
if [ -n "$EMAIL" ] && [ "$FULL_NAME" != "$EMAIL" ]; then
  USER_TEXT="$FULL_NAME ($EMAIL)"
fi

USER_MARKDOWN="$FULL_NAME"
if [ -n "$EMAIL" ]; then
  USER_MARKDOWN="[$FULL_NAME](mailto:$EMAIL)"
fi

if [ -n "$GITHUB_USERNAME" ]; then
  USER_GITHUB="@$GITHUB_USERNAME"
else
  USER_GITHUB="$FULL_NAME"
fi

# Output in requested format
case "$OUTPUT_FORMAT" in
  markdown)
    echo "🤖 Generert med KI av $USER_MARKDOWN med $MODEL i $EDITOR"
    ;;
  GitHub)
    echo "🤖 Generert med KI av $USER_GITHUB med $MODEL i $EDITOR"
    ;;
  JIRA)
    ESCAPED_MODEL=$(json_escape "$MODEL")
    ESCAPED_EDITOR=$(json_escape "$EDITOR")
    if [ "$MENTION" = "yes" ] && [ -n "$JIRA_USER_ID" ]; then
      ESCAPED_JIRA_USER_ID=$(json_escape "$JIRA_USER_ID")
      ESCAPED_FULL_NAME=$(json_escape "$FULL_NAME")
      echo "{\"type\":\"paragraph\",\"content\":[{\"type\":\"text\",\"text\":\"🤖 Generert med KI av \"},{\"type\":\"mention\",\"attrs\":{\"id\":\"$ESCAPED_JIRA_USER_ID\",\"text\":\"@$ESCAPED_FULL_NAME\"}},{\"type\":\"text\",\"text\":\" med $ESCAPED_MODEL i $ESCAPED_EDITOR\"}]}"
    else
      ESCAPED_FULL_NAME=$(json_escape "$FULL_NAME")
      echo "{\"type\":\"paragraph\",\"content\":[{\"type\":\"text\",\"text\":\"🤖 Generert med KI av $ESCAPED_FULL_NAME med $ESCAPED_MODEL i $ESCAPED_EDITOR\",\"marks\":[{\"type\":\"em\"}]}]}"
    fi
    ;;
esac
