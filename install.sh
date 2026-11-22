#!/usr/bin/env bash
set -euo pipefail

source_dir=$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")
data_dir=${XDG_DATA_HOME:-"$HOME/.local/share"}
app_dir=$data_dir/spacemouse
bin_dir=$HOME/.local/bin
service=spacenavd.service
daemon_dir=/usr/local/lib/spacemouse
override=/etc/systemd/system/$service.d/60-spacemouse.conf
config_dir=${XDG_CONFIG_HOME:-"$HOME/.config"}/spacemouse
app_files=(driver.py button_profiles.py onshape_bridge.py install.sh spacemouse VERSION)

fail() {
    printf 'Akita SpaceMouse: %s\n' "$*" >&2
    exit 1
}

lock_installation() {
    exec {lock_fd}<"$data_dir"
    flock -x "$lock_fd"
}

restore_distro_driver() {
    local dry_run=$1 binary backup exec_start was_active=false
    local binaries=()
    for binary in "$daemon_dir"/spacenavd-*; do
        if [[ -f $binary && ! -L $binary && ${binary##*/} =~ ^spacenavd-[0-9]+(\.[0-9]+)+$ ]]; then
            binaries+=("$binary")
        fi
    done

    if [[ -e $override || -L $override ]]; then
        binary=$(sed -n 's/^ExecStart=\(.*\) -d$/\1/p' "$override")
        [[ ! -L $override && $binary == "$daemon_dir"/spacenavd-* ]] \
            && cmp -s "$override" <(printf '[Service]\nType=simple\nPIDFile=\nExecStart=\nExecStart=%s -d\n' "$binary") \
            || fail "The systemd override has local edits at $override."
        [[ -x /usr/bin/spacenavd ]] || fail "Install the distro spacenavd package before restoring its service."
        printf 'Restore the distro spacenavd service by removing %s\n' "$override"
        if ! "$dry_run"; then
            temp_dir=$(mktemp -d)
            trap 'rm -rf -- "$temp_dir"' EXIT
            backup=$temp_dir/override.conf
            cp -- "$override" "$backup"
            if systemctl is-active --quiet "$service"; then
                was_active=true
            fi
            sudo unlink -- "$override"
            if ! reload_distro_driver "$was_active"; then
                sudo install -m 0644 "$backup" "$override"
                sudo systemctl daemon-reload
                if "$was_active"; then sudo systemctl restart "$service"; fi
                fail "Could not restore the distro service. Reinstated the previous override."
            fi
        fi
    fi
    if ! "$dry_run" && (( ${#binaries[@]} )); then
        exec_start=$(systemctl show -p ExecStart --value "$service") \
            || fail "Could not determine which daemon the systemd service uses."
        [[ $exec_start != *"$daemon_dir/"* ]] \
            || fail "A systemd override still uses the local daemon in $daemon_dir."
    fi
    for binary in "${binaries[@]}"; do
        printf 'Remove %s\n' "$binary"
        if ! "$dry_run"; then sudo unlink -- "$binary"; fi
    done
    if ! "$dry_run" && [[ -d $daemon_dir ]]; then
        sudo rmdir --ignore-fail-on-non-empty -- "$daemon_dir"
    fi
}

reload_distro_driver() {
    sudo systemctl daemon-reload || return
    if "$1"; then
        sudo systemctl restart "$service" && wait_for_socket
    fi
}

uninstall() {
    local dry_run=false purge=false restore=false file argument
    local launcher=$bin_dir/spacemouse
    local tool=$app_dir/uv-tools/spacenav-ws
    for argument in "$@"; do
        case $argument in
            --dry-run) dry_run=true ;;
            --purge) purge=true ;;
            --restore-driver) restore=true ;;
            -h|--help)
                printf '%s\n' 'Usage: spacemouse uninstall [--dry-run] [--purge] [--restore-driver]' \
                    'Remove the launcher and its isolated bridge. --purge also removes button profiles.' \
                    '--restore-driver switches any installer-managed upstream daemon back to the distro package.'
                return ;;
            *) fail "Unknown uninstall option $argument. See spacemouse uninstall --help." ;;
        esac
    done
    [[ $EUID != 0 ]] || fail "Run uninstall as the desktop user who installed SpaceMouse."
    if ! "$dry_run" && [[ -d $data_dir ]]; then lock_installation; fi
    [[ ! -L $app_dir && ( $purge == false || ! -L $config_dir ) ]] \
        || fail "The SpaceMouse data or config directory is a symbolic link."
    if "$dry_run"; then printf 'Dry run\n'; fi
    if "$restore"; then restore_distro_driver "$dry_run"; fi

    if [[ -f "$app_dir/.installed" || $(readlink -- "$launcher" 2>/dev/null) == "$app_dir/spacemouse" ]]; then
        printf 'Remove the launcher and isolated bridge in %s\n' "$app_dir"
        if ! "$dry_run"; then
            if [[ -f "$tool/uv-receipt.toml" && ! -L $tool && ! -L "$app_dir/uv-tools" ]]; then
                python3 -c 'from shutil import rmtree; import sys; rmtree(sys.argv[1])' "$tool"
                if [[ -f "$app_dir/uv-tools/.lock" && ! -s "$app_dir/uv-tools/.lock" ]]; then
                    unlink -- "$app_dir/uv-tools/.lock"
                fi
                if cmp -s "$app_dir/uv-tools/.gitignore" <(printf '*'); then
                    unlink -- "$app_dir/uv-tools/.gitignore"
                fi
            fi
            if [[ ! -L "$app_dir/bin" && $(readlink -- "$app_dir/bin/spacenav-ws" 2>/dev/null) == "$tool/bin/spacenav-ws" ]]; then
                unlink -- "$app_dir/bin/spacenav-ws"
            fi
            if [[ $(readlink -- "$launcher" 2>/dev/null) == "$app_dir/spacemouse" ]]; then
                unlink -- "$launcher"
            fi
            for file in "${app_files[@]}" .installed; do
                if [[ -f "$app_dir/$file" || -L "$app_dir/$file" ]]; then
                    unlink -- "$app_dir/$file"
                fi
            done
            for file in "$app_dir/bin" "$app_dir/uv-tools" "$app_dir"; do
                if [[ -d $file && ! -L $file ]]; then rmdir --ignore-fail-on-non-empty -- "$file"; fi
            done
        fi
    else
        printf 'No installed SpaceMouse launcher found.\n'
    fi
    if "$purge"; then
        printf 'Remove saved button profiles in %s\n' "$config_dir"
        if ! "$dry_run"; then
            for file in "$config_dir/buttons.json" "$config_dir/buttons.lock"; do
                if [[ -f $file || -L $file ]]; then unlink -- "$file"; fi
            done
            if [[ -d $config_dir ]]; then rmdir --ignore-fail-on-non-empty -- "$config_dir"; fi
        fi
    fi
}

wait_for_socket() {
    local attempt
    for ((attempt = 0; attempt < 30; attempt++)); do
        if python3 "$source_dir/driver.py" socket 2>/dev/null; then
            return 0
        fi
        sleep 0.2
    done
    return 1
}

if [[ ${1:-} == --uninstall ]]; then
    shift
    uninstall "$@"
    exit 0
fi

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    printf '%s\n' 'Usage: spacemouse install' \
        'Install or update the Linux driver, Onshape bridge, and user launcher.' \
        'Run as your desktop user. The installer uses sudo when it needs to change system packages or services.'
    exit 0
fi
[[ $# == 0 ]] || fail "Usage: spacemouse install"
[[ $EUID != 0 ]] || fail "Run this installer as your desktop user. It uses sudo for system changes."
[[ -d /run/systemd/system ]] || fail "Automatic installation requires Linux with systemd."
[[ -r /etc/os-release ]] || fail "Cannot determine the Linux distribution."
mkdir -p -- "$data_dir"
lock_installation
[[ ! -L $app_dir ]] || fail "The SpaceMouse data directory is a symbolic link."
if [[ -e "$bin_dir/spacemouse" || -L "$bin_dir/spacemouse" ]]; then
    [[ $(readlink -- "$bin_dir/spacemouse") == "$app_dir/spacemouse" ]] \
        || fail "$bin_dir/spacemouse already exists. Move it aside to install this launcher."
fi

# shellcheck source=/dev/null
. /etc/os-release
case " ${ID:-} ${ID_LIKE:-} " in
    *' arch '*)
        manager=(pacman -S --needed)
        runtime_packages=(ca-certificates curl python spacenavd)
        build_packages=(gcc make libx11 libxtst)
        package_installed() { pacman -Q "$1" >/dev/null 2>&1; }
        ;;
    *' debian '*|*' ubuntu '*)
        manager=(apt-get install)
        runtime_packages=(ca-certificates curl python3 spacenavd)
        build_packages=(build-essential libx11-dev libxtst-dev)
        package_installed() { [[ $(dpkg-query -W -f='${Status}' "$1" 2>/dev/null) == 'install ok installed' ]]; }
        ;;
    *' fedora '*)
        manager=(dnf install)
        runtime_packages=(ca-certificates curl python3 spacenavd)
        build_packages=(gcc make libX11-devel libXtst-devel)
        package_installed() {
            # Fedora also provides the curl command in curl-minimal.
            rpm -q "$1" >/dev/null 2>&1 || { [[ $1 == curl ]] && command -v curl >/dev/null; }
        }
        ;;
    *) fail "Automatic setup supports Arch, Debian, Ubuntu, Fedora, and their derivatives." ;;
esac

install_packages() {
    local package
    local missing=()
    for package in "$@"; do
        if ! package_installed "$package"; then
            missing+=("$package")
        fi
    done
    if (( ${#missing[@]} )); then
        if [[ ${manager[0]} == apt-get ]]; then
            sudo apt-get update
        fi
        sudo "${manager[@]}" "${missing[@]}"
    fi
}

daemon_version() {
    local output
    output=$("$1" -V 2>/dev/null) || return 0
    if [[ $output =~ ^spacenavd[[:space:]]+([0-9]+(\.[0-9]+)+)$ ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
    fi
}

version_at_least() {
    [[ -n $1 && $(printf '%s\n' "$1" "$2" | sort -V | tail -n 1) == "$1" ]]
}

use_upstream_daemon() {
    local binary=$daemon_dir/spacenavd-$version
    if [[ $(daemon_version "$binary") != "$version" ]]; then
        printf 'Building spacenavd %s from the verified upstream release.\n' "$version"
        install_packages "${build_packages[@]}"
        download "$archive_url" -o "$temp_dir/spacenavd.tar.gz"
        (cd "$temp_dir" && printf '%s  spacenavd.tar.gz\n' "$checksum" | sha256sum --check --status) \
            || fail "The spacenavd download did not match its release checksum."
        mkdir "$temp_dir/source"
        tar -xzf "$temp_dir/spacenavd.tar.gz" -C "$temp_dir/source" --strip-components=1
        (
            cd "$temp_dir/source"
            ./configure --cfgdir=/etc
            make -j"$(nproc)"
        )
        [[ $(daemon_version "$temp_dir/source/spacenavd") == "$version" ]] \
            || fail "The built spacenavd does not report version $version."
        sudo install -d -m 0755 "$daemon_dir"
        sudo install -m 0755 "$temp_dir/source/spacenavd" "$binary"
    fi

    cat > "$temp_dir/override.conf" <<UNIT
[Service]
Type=simple
PIDFile=
ExecStart=
ExecStart=$binary -d
UNIT
    if cmp -s "$temp_dir/override.conf" "$override"; then
        return
    fi
    if [[ -e $override ]]; then
        cp -- "$override" "$temp_dir/previous.conf"
    fi
    sudo install -d -m 0755 "${override%/*}"
    sudo install -m 0644 "$temp_dir/override.conf" "$override"
    if sudo systemctl daemon-reload && sudo systemctl restart "$service" && wait_for_socket; then
        return
    fi

    printf 'The upstream daemon did not start. Restoring the previous service configuration.\n' >&2
    if [[ -e "$temp_dir/previous.conf" ]]; then
        sudo install -m 0644 "$temp_dir/previous.conf" "$override"
    else
        sudo rm -- "$override"
    fi
    sudo systemctl daemon-reload
    sudo systemctl restart "$service"
    fail "Could not start spacenavd $version. See journalctl -u $service."
}

download() {
    curl --proto '=https' --proto-redir '=https' --fail --silent --show-error \
        --location --retry 2 --connect-timeout 10 --max-time 120 "$@"
}

install_packages "${runtime_packages[@]}"
temp_dir=$(mktemp -d)
trap 'rm -rf -- "$temp_dir"' EXIT

printf 'Checking the latest upstream spacenavd release.\n'
download https://api.github.com/repos/FreeSpacenav/spacenavd/releases/latest -o "$temp_dir/release.json" \
    || fail "Could not check the FreeSpacenav release on GitHub. Check your connection and retry."
release=$(python3 - "$temp_dir/release.json" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as metadata:
    release = json.load(metadata)
tag = release.get("tag_name", "")
if not re.fullmatch(r"v[0-9]+(?:\.[0-9]+)+", tag):
    sys.exit("Could not identify the latest stable spacenavd version.")
version = tag[1:]
name = f"spacenavd-{version}.tar.gz"
url = f"https://github.com/FreeSpacenav/spacenavd/releases/download/{tag}/{name}"
for asset in release["assets"]:
    digest = re.fullmatch(r"sha256:([0-9a-f]{64})", asset.get("digest") or "")
    if asset.get("browser_download_url") == url and digest:
        print(version, url, digest[1])
        break
else:
    sys.exit(f"No verifiable source archive was published for spacenavd {version}.")
PY
)
read -r version archive_url checksum <<< "$release"

# If a newer distro package is available, it takes effect through the normal
# package manager. Retain any previously selected upstream binary.
if [[ ! -e $override ]] && version_at_least "$(daemon_version /usr/bin/spacenavd)" "$version"; then
    printf 'The distribution package already provides spacenavd %s or newer.\n' "$version"
else
    use_upstream_daemon
fi
if ! systemctl is-enabled --quiet "$service" || ! systemctl is-active --quiet "$service"; then
    sudo systemctl enable --now "$service" || fail "Could not enable spacenavd. See journalctl -u $service."
fi
wait_for_socket || fail "The Onshape socket did not become available. See journalctl -u $service."

if command -v uv >/dev/null; then
    uv=$(command -v uv)
else
    uv=$bin_dir/uv
    if [[ ! -x $uv ]]; then
        printf 'Installing uv for %s.\n' "$(id -un)"
        download https://astral.sh/uv/install.sh -o "$temp_dir/uv-install.sh"
        UV_INSTALL_DIR="$bin_dir" UV_NO_MODIFY_PATH=1 sh "$temp_dir/uv-install.sh"
    fi
fi
printf 'Installing the latest spacenav-ws bridge.\n'
UV_TOOL_DIR="$app_dir/uv-tools" UV_TOOL_BIN_DIR="$app_dir/bin" \
    "$uv" --quiet tool install --upgrade --python '>=3.11' spacenav-ws

install -d -m 0755 "$app_dir" "$bin_dir"
for file in "${app_files[@]}"; do
    if [[ ! "$source_dir/$file" -ef "$app_dir/$file" ]]; then
        mode=0644
        if [[ -x "$source_dir/$file" ]]; then mode=0755; fi
        install -m "$mode" "$source_dir/$file" "$app_dir/$file"
    fi
done
touch -- "$app_dir/.installed"
if [[ ! -L "$bin_dir/spacemouse" ]]; then
    ln -s -- "$app_dir/spacemouse" "$bin_dir/spacemouse"
fi

printf '\nInstalled Akita SpaceMouse for Linux %s.\n' "$(<"$app_dir/VERSION")"
printf 'For first-time Onshape setup, run ./spacemouse to open the bridge test page.\n'
printf 'After setup, run spacemouse onshape or %q onshape.\n' "$bin_dir/spacemouse"
printf 'Use spacemouse doctor to check your device and spacemouse --help for all commands.\n'
