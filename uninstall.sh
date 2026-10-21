#!/usr/bin/env bash
#
# Remove the sd_kokoro module for the current user.
#
#   ./uninstall.sh            remove module + config, restore default module
#   ./uninstall.sh --keep-config
#
# speechd.conf is backed up before it is edited.

set -euo pipefail

KEEP_CONFIG=0
for arg in "$@"; do
    case "$arg" in
        --keep-config) KEEP_CONFIG=1 ;;
        -h|--help)
            sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "unknown option: $arg" >&2
            exit 2
            ;;
    esac
done

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
MODULE_DIR="$(realpath -m "$DATA_HOME/../libexec/speech-dispatcher-modules")"
CONFIG_DIR="$CONFIG_HOME/speech-dispatcher"
MODULE_CONFIG="$CONFIG_DIR/modules/kokoro.conf"
SPEECHD_CONF="$CONFIG_DIR/speechd.conf"

say() { echo "==> $*"; }

if [ -f "$MODULE_DIR/sd_kokoro" ]; then
    rm -f "$MODULE_DIR/sd_kokoro"
    say "removed $MODULE_DIR/sd_kokoro"
fi

if [ "$KEEP_CONFIG" -eq 0 ] && [ -f "$MODULE_CONFIG" ]; then
    rm -f "$MODULE_CONFIG"
    say "removed $MODULE_CONFIG"
fi

if [ -f "$SPEECHD_CONF" ]; then
    if grep -qE '^[[:space:]]*AddModule[[:space:]]+"kokoro"' "$SPEECHD_CONF"; then
        BACKUP="$SPEECHD_CONF.bak-$(date +%Y%m%d-%H%M%S)"
        cp "$SPEECHD_CONF" "$BACKUP"
        say "backed up speechd.conf to $BACKUP"
        sed -i -E '/^[[:space:]]*AddModule[[:space:]]+"kokoro"/d' "$SPEECHD_CONF"
        sed -i -E '/^# Added by sd-kokoro$/d' "$SPEECHD_CONF"
        say "removed AddModule line"
    fi

    if grep -qE '^[[:space:]]*DefaultModule[[:space:]]+"?kokoro"?' "$SPEECHD_CONF"; then
        MARKER="$CONFIG_DIR/.sd-kokoro-previous-default"
        sed -i -E '/^[[:space:]]*DefaultModule[[:space:]]+"?kokoro"?/d' "$SPEECHD_CONF"
        if [ -s "$MARKER" ]; then
            PREV=$(cat "$MARKER")
            if ! grep -qxF "$PREV" "$SPEECHD_CONF"; then
                printf '\n%s\n' "$PREV" >> "$SPEECHD_CONF"
            fi
            rm -f "$MARKER"
            say "restored previous DefaultModule: $PREV"
        elif grep -qE '^#[[:space:]]*DefaultModule' "$SPEECHD_CONF"; then
            sed -i -E '0,/^#[[:space:]]*(DefaultModule)/s//\1/' "$SPEECHD_CONF"
            say "restored the previously commented DefaultModule"
        else
            say "removed DefaultModule kokoro (no previous default found)"
        fi
    fi
    rm -f "$CONFIG_DIR/.sd-kokoro-previous-default"
fi

if systemctl --user is-active --quiet speech-dispatcher 2>/dev/null; then
    say "restarting speech-dispatcher.service"
    systemctl --user restart speech-dispatcher
fi

say "uninstalled"
