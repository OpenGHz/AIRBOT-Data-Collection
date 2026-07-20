#!/bin/sh
set -eu
# Offline installer for Pixi.
# Derived from the official https://pixi.sh/install.sh (v0.73.0).
# The only change vs. the official script is where the archive comes
# from: instead of downloading it over the network, this installs from a
# pre-downloaded local archive. Everything after the archive is obtained
# (verification, extraction, binary placement, PATH update) is identical
# to the official installer.
#
# Usage:
#   1. Download the matching release asset from
#      https://github.com/prefix-dev/pixi/releases
#      (this Linux x86_64 box -> pixi-x86_64-unknown-linux-musl.tar.gz)
#   2. Put it next to this script, or set PIXI_DOWNLOAD_FILE=/path/to/archive
#   3. Run:  sh install_pixi_offline.sh
#
# Same env vars as the official script: PIXI_VERSION, PIXI_HOME,
# PIXI_BIN_DIR, PIXI_ARCH, PIXI_REPOURL, PIXI_NO_PATH_UPDATE.
# Offline-only: PIXI_DOWNLOAD_FILE (explicit archive path),
#               PIXI_DOWNLOAD_DIR  (directory to search for the archive).

__wrap__() {

    VERSION="${PIXI_VERSION:-latest}"
    PIXI_HOME="${PIXI_HOME:-$HOME/.pixi}"
    case "$PIXI_HOME" in
    '~' | '~'/*) PIXI_HOME="${HOME-}${PIXI_HOME#\~}" ;; # expand tilde
    esac
    PIXI_BIN_DIR="${PIXI_BIN_DIR:-$PIXI_HOME/bin}"

    REPOURL="${PIXI_REPOURL:-https://github.com/prefix-dev/pixi}"
    PLATFORM="$(uname -s)"
    ARCH="${PIXI_ARCH:-$(uname -m)}"
    IS_MSYS=false

    if [ "${PLATFORM-}" = "Darwin" ]; then
        PLATFORM="apple-darwin"
    elif [ "${PLATFORM-}" = "Linux" ]; then
        if [ "${ARCH-}" = "riscv64" ]; then
            PLATFORM="unknown-linux-gnu"
        else
            PLATFORM="unknown-linux-musl"
        fi
    elif [ "$(uname -o)" = "Msys" ]; then
        IS_MSYS=true
        PLATFORM="pc-windows-msvc"
    fi
    case "${ARCH-}" in
    arm64 | aarch64) ARCH="aarch64" ;;
    riscv64) ARCH="riscv64gc" ;;
    esac

    BINARY="pixi-${ARCH}-${PLATFORM}"
    if $IS_MSYS; then
        EXTENSION=".zip"
        hash unzip 2>/dev/null || EXTENSION=".exe"
    else
        EXTENSION=".tar.gz"
        hash tar 2>/dev/null || EXTENSION=''
    fi

    ARCHIVE_NAME="${BINARY}${EXTENSION-}"

    # --- OFFLINE: resolve a local archive instead of downloading -----------
    # Locate the pre-downloaded archive. Precedence:
    #   1. PIXI_DOWNLOAD_FILE  - explicit path to the archive
    #   2. PIXI_DOWNLOAD_DIR   - directory containing the archive
    #   3. the directory this script lives in
    #   4. the current working directory
    SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"

    SOURCE_FILE=""
    if [ -n "${PIXI_DOWNLOAD_FILE:-}" ]; then
        SOURCE_FILE="$PIXI_DOWNLOAD_FILE"
    else
        for dir in "${PIXI_DOWNLOAD_DIR:-}" "${SCRIPT_DIR:-}" "$(pwd)"; do
            [ -n "$dir" ] || continue
            if [ -f "$dir/$ARCHIVE_NAME" ]; then
                SOURCE_FILE="$dir/$ARCHIVE_NAME"
                break
            fi
        done
    fi

    printf "This script will install Pixi (%s) from a local archive.\nExpecting asset: %s\n" "$VERSION" "$ARCHIVE_NAME"

    if [ -z "$SOURCE_FILE" ] || [ ! -f "$SOURCE_FILE" ]; then
        echo "error: could not find the local archive '$ARCHIVE_NAME'." >&2
        echo "       Searched: \$PIXI_DOWNLOAD_FILE, \$PIXI_DOWNLOAD_DIR, '${SCRIPT_DIR:-.}', '$(pwd)'." >&2
        echo "       Download it from ${REPOURL%/}/releases and place it there," >&2
        echo "       or set PIXI_DOWNLOAD_FILE=/path/to/$ARCHIVE_NAME." >&2
        exit 1
    fi

    echo "Using local archive: $SOURCE_FILE"

    # Copy into a temp file so the extraction logic below is byte-for-byte
    # identical to the official script (which extracts from "$TEMP_FILE").
    TEMP_FILE="$(mktemp "${TMPDIR:-/tmp}/.pixi_install.XXXXXXXX")"

    cleanup() {
        rm -f "$TEMP_FILE"
    }

    trap cleanup EXIT

    cp -f "$SOURCE_FILE" "$TEMP_FILE"
    # --- END OFFLINE section ----------------------------------------------

    # Check that file was correctly created (https://github.com/prefix-dev/pixi/issues/446)
    if [ ! -s "$TEMP_FILE" ]; then
        echo "error: temporary file ${TEMP_FILE} not correctly created." >&2
        echo "       As a workaround, you can try set TMPDIR env variable to directory with write permissions." >&2
        exit 1
    fi

    # Extract pixi from the downloaded file
    mkdir -p "$PIXI_BIN_DIR"
    if [ "${EXTENSION-}" = ".zip" ]; then
        unzip "$TEMP_FILE" -d "$PIXI_BIN_DIR"
    elif [ "${EXTENSION-}" = ".tar.gz" ]; then
        # Extract to a temporary directory first
        TEMP_DIR=$(mktemp -d)
        tar -xzf "$TEMP_FILE" -C "$TEMP_DIR"

        # Find and move the `pixi` binary, making sure to handle the case where it's in a subdirectory
        if [ -f "$TEMP_DIR/pixi" ]; then
            mv "$TEMP_DIR/pixi" "$PIXI_BIN_DIR/"
        else
            mv "$(find "$TEMP_DIR" -type f -name pixi)" "$PIXI_BIN_DIR/"
        fi

        chmod +x "$PIXI_BIN_DIR/pixi"
        rm -rf "$TEMP_DIR"
    elif [ "${EXTENSION-}" = ".exe" ]; then
        cp -f "$TEMP_FILE" "$PIXI_BIN_DIR/pixi.exe"
    else
        chmod +x "$TEMP_FILE"
        cp -f "$TEMP_FILE" "$PIXI_BIN_DIR/pixi"
    fi

    echo "The 'pixi' binary is installed into '${PIXI_BIN_DIR}'"

    # shell update can be suppressed by `PIXI_NO_PATH_UPDATE` env var
    if [ -n "${PIXI_NO_PATH_UPDATE:-}" ]; then
        echo "No path update because PIXI_NO_PATH_UPDATE is set"
    else
        update_shell() {
            FILE="$1"
            LINE="$2"

            # Create the file if it doesn't exist
            if [ ! -f "$FILE" ]; then
                touch "$FILE"
            fi

            # Append the line if not already present
            if ! grep -Fxq "$LINE" "$FILE"; then
                echo "Updating '${FILE}'"
                echo >>"$FILE"
                echo "$LINE" >>"$FILE"
                echo "Please restart or source your shell."
            fi
        }

        case "$(basename "${SHELL-}")" in
        bash)
            # Default to bashrc as that is used in non login shells instead of the profile.
            LINE="export PATH=\"${PIXI_BIN_DIR}:\$PATH\""
            update_shell ~/.bashrc "$LINE"
            ;;

        fish)
            # Use 'set -gx PATH' for compatibility with Fish < 3.2.0 (which lacks fish_add_path)
            LINE="set -gx PATH \"${PIXI_BIN_DIR}\" \$PATH"
            update_shell ~/.config/fish/config.fish "$LINE"
            ;;

        zsh)
            LINE="export PATH=\"${PIXI_BIN_DIR}:\$PATH\""
            update_shell ~/.zshrc "$LINE"
            ;;

        tcsh)
            LINE="set path = ( ${PIXI_BIN_DIR} \$path )"
            update_shell ~/.tcshrc "$LINE"
            ;;

        '')
            echo "warn: Could not detect shell type." >&2
            echo "      Please permanently add '${PIXI_BIN_DIR}' to your \$PATH to enable the 'pixi' command." >&2
            ;;

        *)
            echo "warn: Could not update shell $(basename "$SHELL")" >&2
            echo "      Please permanently add '${PIXI_BIN_DIR}' to your \$PATH to enable the 'pixi' command." >&2
            ;;
        esac
    fi
} && __wrap__
