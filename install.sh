#!/usr/bin/env bash
#
# Install spd_kokoro for the current user.
#
#   ./install.sh              add the module, keep the current default
#   ./install.sh --default    add the module and make it the default
#   ./install.sh --dry-run    show what would be done
#
# The module binary goes to ~/.local/libexec/speech-dispatcher-modules
# and the config to ~/.config/speech-dispatcher/modules.  speechd.conf is
# backed up before it is edited.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SET_DEFAULT=0
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --default) SET_DEFAULT=1 ;;
        --dry-run) DRY_RUN=1 ;;
        -h|--help)
            sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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
MODULE_CONFIG_DIR="$CONFIG_DIR/modules"
MODULE_CONFIG="$MODULE_CONFIG_DIR/kokoro.conf"
SPEECHD_CONF="$CONFIG_DIR/speechd.conf"
SYSTEM_CONF="/etc/speech-dispatcher/speechd.conf"

say() { echo "==> $*"; }
run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "    [dry-run] $*"
    else
        "$@"
    fi
}

say "module directory: $MODULE_DIR"
say "config directory: $MODULE_CONFIG_DIR"

run mkdir -p "$MODULE_DIR" "$MODULE_CONFIG_DIR"
run install -m 0755 "$ROOT/spd_kokoro" "$MODULE_DIR/spd_kokoro"

if [ -f "$MODULE_CONFIG" ]; then
    say "keeping existing $MODULE_CONFIG"
else
    run install -m 0644 "$ROOT/kokoro.conf" "$MODULE_CONFIG"
    say "installed $MODULE_CONFIG"
fi

# --- speechd.conf ---------------------------------------------------------
if [ ! -f "$SPEECHD_CONF" ]; then
    if [ -f "$SYSTEM_CONF" ]; then
        run mkdir -p "$CONFIG_DIR"
        run cp "$SYSTEM_CONF" "$SPEECHD_CONF"
        say "created $SPEECHD_CONF from $SYSTEM_CONF"
    else
        run mkdir -p "$CONFIG_DIR"
        run touch "$SPEECHD_CONF"
        say "created empty $SPEECHD_CONF"
    fi
fi

if ! grep -qE '^[[:space:]]*AddModule[[:space:]]+"kokoro"' "$SPEECHD_CONF" 2>/dev/null; then
    BACKUP="$SPEECHD_CONF.bak-$(date +%Y%m%d-%H%M%S)"
    run cp "$SPEECHD_CONF" "$BACKUP"
    say "backed up speechd.conf to $BACKUP"
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "    [dry-run] append: AddModule \"kokoro\" \"spd_kokoro\" \"kokoro.conf\""
    else
        printf '\n# Added by spd-kokoro\nAddModule "kokoro" "spd_kokoro" "kokoro.conf"\n' \
            >> "$SPEECHD_CONF"
    fi
    say "added AddModule line"
else
    say "AddModule line already present"
fi

if [ "$SET_DEFAULT" -eq 1 ]; then
    MARKER="$CONFIG_DIR/.spd-kokoro-previous-default"
    if grep -qE '^[[:space:]]*DefaultModule[[:space:]]+"?kokoro"?' "$SPEECHD_CONF"; then
        say "kokoro is already the default module"
        # Record the previous default for uninstall.sh, if we can find it.
        if [ ! -f "$MARKER" ]; then
            PREV=$(grep -m1 -E '^#[[:space:]]*DefaultModule' "$SPEECHD_CONF" || true)
            PREV=$(printf '%s' "$PREV" | sed -E 's/^#[[:space:]]*//')
            if [ "$DRY_RUN" -eq 0 ] && [ -n "$PREV" ]; then
                printf '%s\n' "$PREV" > "$MARKER"
            fi
        fi
    else
        BACKUP="$SPEECHD_CONF.bak-$(date +%Y%m%d-%H%M%S)"
        run cp "$SPEECHD_CONF" "$BACKUP"
        say "backed up speechd.conf to $BACKUP"
        PREV=$(grep -m1 -E '^[[:space:]]*DefaultModule' "$SPEECHD_CONF" || true)
        if [ "$DRY_RUN" -eq 0 ] && [ ! -f "$MARKER" ]; then
            printf '%s\n' "$PREV" > "$MARKER"
        fi
        if [ "$DRY_RUN" -eq 1 ]; then
            echo "    [dry-run] remove existing DefaultModule and set kokoro"
        else
            sed -i -E '/^[[:space:]]*DefaultModule/d' "$SPEECHD_CONF"
            printf '\nDefaultModule "kokoro"\n' >> "$SPEECHD_CONF"
        fi
        say "set kokoro as DefaultModule"
    fi
fi

# --- restart the server ---------------------------------------------------
if [ "$DRY_RUN" -eq 0 ]; then
    if systemctl --user is-active --quiet speech-dispatcher 2>/dev/null; then
        say "restarting speech-dispatcher.service"
        systemctl --user restart speech-dispatcher
        sleep 1
    else
        say "speech-dispatcher is not running; it will pick up the new config on next start"
    fi
fi

say "installed"
echo
echo "Try it:"
echo "    spd-say -o kokoro -w \"Hello from Kokoro\""
echo "    spd-say -o kokoro -y am_michael -w \"A different voice\""
echo "    spd-say -L -o kokoro          # list voices"
if [ "$SET_DEFAULT" -eq 0 ]; then
    echo
    echo "kokoro is not the default module.  To make screen readers and other"
    echo "clients use it:  ./install.sh --default"
fi
