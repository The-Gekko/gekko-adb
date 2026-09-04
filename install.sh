#!/bin/bash
# Gekko ADB Studio - instalador Arch/Garuda (pacman) y Solus (eopkg).
# Instala en directorios XDG (nunca root, nunca rutas hardcodeadas de usuario).
# Funciona desde un checkout, desde la copia instalada y por pipe (curl | bash).
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RESET='\033[0m'

# Con "curl … | bash" BASH_SOURCE está vacío: en ese caso no hay checkout y
# las fuentes se descargan (modo standalone).
SELF_PATH="${BASH_SOURCE[0]:-}"
if [[ -n "$SELF_PATH" && -f "$SELF_PATH" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$SELF_PATH")")" && pwd)"
else
    SCRIPT_DIR=""
fi
SRC_DIR="$SCRIPT_DIR"
GEKKO_ADB_TARBALL="${GEKKO_ADB_TARBALL:-https://github.com/The-Gekko/gekko-adb/archive/refs/heads/main.tar.gz}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
APP_DATA_ROOT="$DATA_HOME/gekko-adb"
INSTALL_DIR="$APP_DATA_ROOT/app"
ENV_FILE="$APP_DATA_ROOT/.env"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/512x512/apps"
METAINFO_DIR="$DATA_HOME/metainfo"
DESKTOP_FILE="$APP_DIR/com.gekko.adb.desktop"
ICON_FILE="$ICON_DIR/gekko-adb.png"
METAINFO_FILE="$METAINFO_DIR/com.gekko.adb.metainfo.xml"
LEGACY_DESKTOP_FILE="$APP_DIR/GekkoADB.desktop"
LOG_DIR="$STATE_HOME/gekko-adb/logs"

# Detección de distribución (Arch/Garuda/Manjaro → pacman, Solus → eopkg)
DISTRO="unknown"
if [[ -r /etc/os-release ]]; then
    . /etc/os-release
    case "${ID:-}" in
        arch|garuda|manjaro|endeavouros|cachyos) DISTRO="arch" ;;
        solus) DISTRO="solus" ;;
    esac
    case " ${ID_LIKE:-} " in
        *" arch "*) [[ "$DISTRO" == unknown ]] && DISTRO="arch" ;;
    esac
fi

# android-udev aporta las reglas 51-android.rules en Arch (android-tools no).
REQUIRED_PACKAGES=(
    python
    python-gobject
    gtk3
    gtk4
    android-tools
    android-udev
    scrcpy
    glib2
    xdg-utils
    xdg-user-dirs
    curl
)
OPTIONAL_PACKAGES=(matugen)

if [[ "$DISTRO" == "solus" ]]; then
    # En Solus 'python' es Python 2: el intérprete real es 'python3'.
    REQUIRED_PACKAGES=(
        python3
        python-gobject
        libgtk-3
        libgtk-4
        android-tools
        scrcpy
        glib2
        xdg-utils
        xdg-user-dirs
        curl
    )
    OPTIONAL_PACKAGES=(matugen)
fi

INTEGRATION_TARGETS=(
    "$BIN_DIR/gekko-adb"
    "$DESKTOP_FILE"
    "$ICON_FILE"
    "$METAINFO_FILE"
)

ASSUME_YES=false
CHECK_ONLY=false
INSTALL_DEPS=true
DO_UNINSTALL=false

info()  { echo -e "${CYAN}[i]${RESET} $*"; }
ok()    { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()  { echo -e "${YELLOW}[!]${RESET} $*"; }
fail()  { echo -e "${RED}[✗]${RESET} $*" >&2; }

usage() {
    cat <<EOF
Gekko ADB Studio - instalador Arch/Garuda (pacman) y Solus (eopkg)

Uso: ./install.sh [opciones]
  o:  curl -fsSL https://raw.githubusercontent.com/The-Gekko/gekko-adb/main/install.sh | bash

Opciones:
  --check         Verificar el entorno sin escribir nada
  --uninstall     Eliminar la app (conserva config y logs)
  --no-deps       No instalar dependencias con el gestor de paquetes (tampoco toca udev)
  --assume-yes    Confirmar la instalación de dependencias automáticamente
  --help, -h      Mostrar esta ayuda

Tras instalar, desinstala con:
  ~/.local/share/gekko-adb/app/install.sh --uninstall

Distribución detectada: $DISTRO
Dependencias requeridas: ${REQUIRED_PACKAGES[*]}
Dependencias opcionales: ${OPTIONAL_PACKAGES[*]} (tema Matugen)
EOF
}

for arg in "$@"; do
    case "$arg" in
        --check) CHECK_ONLY=true ;;
        --uninstall) DO_UNINSTALL=true ;;
        --no-deps) INSTALL_DEPS=false ;;
        --assume-yes) ASSUME_YES=true ;;
        --help|-h) usage; exit 0 ;;
        *) warn "Argumento desconocido: $arg"; usage; exit 1 ;;
    esac
done

if [[ "$(id -u)" -eq 0 ]]; then
    fail "No ejecutes el instalador como root. Usa tu usuario normal."
    exit 1
fi

if ! [[ -t 0 ]]; then
    ASSUME_YES=true
    warn "Entrada no interactiva (p. ej. curl | bash); se asume --assume-yes."
fi

if [[ "$DISTRO" == "unknown" ]]; then
    warn "Distribución no reconocida; asumo Arch (pacman)."
    DISTRO="arch"
fi

# ------------------------------------------------------------- desinstalar
# Va antes de cualquier comprobación de dependencias: desinstalar nunca debe
# instalar paquetes ni pedir sudo.
if $DO_UNINSTALL; then
    info "Desinstalando Gekko ADB Studio…"
    for target in "${INTEGRATION_TARGETS[@]}"; do
        if [[ -e "$target" ]]; then
            rm -f "$target" && ok "Eliminado: $target"
        fi
    done
    if [[ -d "$INSTALL_DIR" ]]; then
        rm -rf "$INSTALL_DIR" && ok "Eliminado: $INSTALL_DIR"
    fi
    if [[ -f "$ENV_FILE" ]]; then
        rm -f "$ENV_FILE" && ok "Eliminado: $ENV_FILE"
    fi
    shopt -s nullglob
    for bak in "$APP_DATA_ROOT"/app.bak.*; do
        rm -rf "$bak" && ok "Eliminado backup: $bak"
    done
    shopt -u nullglob
    if [[ -d "$APP_DATA_ROOT" && -z "$(ls -A "$APP_DATA_ROOT" 2>/dev/null)" ]]; then
        rmdir "$APP_DATA_ROOT" 2>/dev/null || true
    fi
    info "Config, logs y presets se conservan en $CONFIG_HOME/gekko-adb y $LOG_DIR."
    ok "Desinstalación completada."
    exit 0
fi

check_package() {
    if [[ "$DISTRO" == "solus" ]]; then
        # 'eopkg list-installed' imprime "nombre - resumen": se compara solo
        # la primera columna. 'eopkg info' responde OK con solo existir en
        # el repo, aunque no esté instalado.
        eopkg list-installed 2>/dev/null | awk '{print $1}' | grep -qx -- "$1"
    else
        pacman -Q "$1" >/dev/null 2>&1
    fi
}

install_deps() {
    if [[ "$DISTRO" == "solus" ]]; then
        sudo eopkg install -y "${MISSING[@]}"
    else
        sudo pacman -S --needed --noconfirm "${MISSING[@]}"
    fi
}

# ------------------------------------------------------------- diagnóstico
info "Comprobando entorno…"
MISSING=()
for pkg in "${REQUIRED_PACKAGES[@]}"; do
    if ! check_package "$pkg"; then
        MISSING+=("$pkg")
    fi
done
OPT_PRESENT=()
for pkg in "${OPTIONAL_PACKAGES[@]}"; do
    if check_package "$pkg"; then
        OPT_PRESENT+=("$pkg")
    fi
done

if [[ ${#MISSING[@]} -eq 0 ]]; then
    ok "Todas las dependencias requeridas están instaladas."
else
    warn "Faltan: ${MISSING[*]}"
fi
if [[ ${#OPT_PRESENT[@]} -gt 0 ]]; then
    ok "Opcionales presentes: ${OPT_PRESENT[*]}"
else
    warn "Matugen no está instalado (el tema matugen se desactivará automáticamente)."
fi

if [[ -x "$BIN_DIR/gekko-adb" ]]; then
    ok "Launcher existente: $BIN_DIR/gekko-adb"
fi

if [[ -f "$LEGACY_DESKTOP_FILE" ]]; then
    warn "Se reemplazará el launcher web legacy: $LEGACY_DESKTOP_FILE"
fi

if [[ -z "$SRC_DIR" ]]; then
    info "Modo standalone (sin checkout): las fuentes se descargarán de $GEKKO_ADB_TARBALL"
fi

if $CHECK_ONLY; then
    ok "Verificación completa (modo --check, no se escribió nada)."
    exit 0
fi

# ------------------------------------------------------------- dependencias
if $INSTALL_DEPS && [[ ${#MISSING[@]} -gt 0 ]]; then
    if ! $ASSUME_YES; then
        read -r -p "¿Instalar dependencias con $([ "$DISTRO" == "solus" ] && echo eopkg || echo pacman)? [s/N] " resp
        if [[ "$resp" != "s" && "$resp" != "S" ]]; then
            fail "Abortado por el usuario."
            exit 1
        fi
    fi
    info "Instalando: ${MISSING[*]}"
    install_deps
fi

# ------------------------------------------------------------- fuentes
# El script funciona desde un checkout (SRC_DIR = SCRIPT_DIR), desde la copia
# instalada (se copia a un directorio temporal antes de tocar INSTALL_DIR) o
# standalone vía curl/wget/python (descarga el tarball del repo).
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

sources_available() {
    [[ -n "$SRC_DIR" && -f "$SRC_DIR/gekko_adb_core.py" ]]
}

fetch_sources() {
    local tar_file src
    info "Modo standalone: descargando fuentes del repo…"
    tar_file="$TMP_ROOT/gekko-adb.tar.gz"
    if command -v curl >/dev/null 2>&1; then
        if ! curl -fsSL "$GEKKO_ADB_TARBALL" -o "$tar_file"; then
            fail "No se pudo descargar $GEKKO_ADB_TARBALL (revisa la red o GEKKO_ADB_TARBALL)."
            exit 1
        fi
    elif command -v wget >/dev/null 2>&1; then
        if ! wget -qO "$tar_file" "$GEKKO_ADB_TARBALL"; then
            fail "No se pudo descargar $GEKKO_ADB_TARBALL (revisa la red o GEKKO_ADB_TARBALL)."
            exit 1
        fi
    else
        if ! python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' \
                "$GEKKO_ADB_TARBALL" "$tar_file"; then
            fail "No se pudo descargar $GEKKO_ADB_TARBALL (revisa la red o GEKKO_ADB_TARBALL)."
            exit 1
        fi
    fi
    if ! tar -xzf "$tar_file" -C "$TMP_ROOT"; then
        fail "El archivo descargado no es un tarball válido."
        exit 1
    fi
    src="$(find "$TMP_ROOT" -maxdepth 2 -name 'gekko_adb_core.py' -print -quit)"
    if [[ -z "$src" ]]; then
        fail "No se pudo obtener el código del proyecto. Revisa la red o GEKKO_ADB_TARBALL."
        exit 1
    fi
    SRC_DIR="$(dirname "$src")"
    ok "Fuentes obtenidas: $SRC_DIR"
}

stage_sources() {
    # Reinstalar desde la copia instalada: copiar primero a temporal para no
    # mover el propio origen al backup.
    local staging="$TMP_ROOT/src"
    mkdir -p "$staging"
    cp -r "$SRC_DIR/." "$staging/"
    SRC_DIR="$staging"
    info "Reinstalando desde la copia instalada (copia temporal en $staging)."
}

# ------------------------------------------------------------- instalación
if ! sources_available; then
    fetch_sources
fi
if [[ "$(readlink -f "$SRC_DIR")" == "$(readlink -f "$INSTALL_DIR" 2>/dev/null || echo "$INSTALL_DIR")" ]]; then
    stage_sources
fi

info "Instalando en $INSTALL_DIR…"
mkdir -p "$APP_DATA_ROOT" "$BIN_DIR" "$APP_DIR" "$ICON_DIR" "$METAINFO_DIR" "$LOG_DIR"

BACKUP_DIR=""
if [[ -d "$INSTALL_DIR" && -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
    shopt -s nullglob
    for old in "$APP_DATA_ROOT"/app.bak.*; do
        rm -rf "$old"
    done
    shopt -u nullglob
    BACKUP_DIR="${APP_DATA_ROOT}/app.bak.$(date +%s)"
    mv "$INSTALL_DIR" "$BACKUP_DIR"
    warn "Backup de la versión anterior: $BACKUP_DIR (se conserva solo el último)"
fi

install_core() {
    # Cada copia se comprueba: 'set -e' no actúa dentro de 'if ! install_core'.
    mkdir -p "$INSTALL_DIR/bin" "$INSTALL_DIR/assets" || return 1
    local f
    for f in gekko_adb_core.py gekko_adb_theme.py gekko-adb-gtk4.py gekko-adb-gtk3.py \
             adb_commands.json debloat_presets.json install.sh; do
        cp "$SRC_DIR/$f" "$INSTALL_DIR/$f" || { fail "Falta $f en las fuentes."; return 1; }
    done
    cp "$SRC_DIR/bin/gekko-adb" "$INSTALL_DIR/bin/gekko-adb" || { fail "Falta bin/gekko-adb."; return 1; }
    cp "$SRC_DIR/assets/gekko-adb.png" "$INSTALL_DIR/assets/gekko-adb.png" || { fail "Falta assets/gekko-adb.png."; return 1; }
    cp "$SRC_DIR/assets/gekko-adb-512.png" "$INSTALL_DIR/assets/gekko-adb-512.png" || { fail "Falta assets/gekko-adb-512.png."; return 1; }
    chmod +x "$INSTALL_DIR/bin/gekko-adb" "$INSTALL_DIR/install.sh" || return 1
    return 0
}

if ! install_core; then
    fail "Falló la copia de archivos."
    if [[ -n "$BACKUP_DIR" && -d "$BACKUP_DIR" ]]; then
        rm -rf "$INSTALL_DIR"
        mv "$BACKUP_DIR" "$INSTALL_DIR"
        warn "Restaurada la versión anterior (rollback)."
    fi
    exit 1
fi

# Launcher en PATH -> app instalada (no al checkout)
cat > "$BIN_DIR/gekko-adb" <<EOF
#!/bin/bash
export GEKKO_ADB_PROJECT_DIR="$INSTALL_DIR"
exec "$INSTALL_DIR/bin/gekko-adb" "\$@"
EOF
chmod +x "$BIN_DIR/gekko-adb"
ok "Launcher: $BIN_DIR/gekko-adb"

# Desktop entry (ID com.gekko.adb). Exec entre comillas por si HOME tiene espacios.
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Gekko ADB Studio
Comment=Master Suite de control ADB para Linux (GTK 3/4)
Exec="$BIN_DIR/gekko-adb"
Icon=gekko-adb
Terminal=false
Categories=Development;System;Utility;
Keywords=ADB;Android;Debloat;Samsung;Xiaomi;Scrcpy;Gekko;
StartupWMClass=com.gekko.adb
EOF
ok "Desktop entry: $DESKTOP_FILE"

# Icono
cp "$SRC_DIR/assets/gekko-adb-512.png" "$ICON_FILE"
ok "Ícono: $ICON_FILE"

# La caché de íconos de usuario solo tiene sentido si existe index.theme.
if command -v gtk-update-icon-cache >/dev/null 2>&1 && [[ -f "$DATA_HOME/icons/hicolor/index.theme" ]]; then
    gtk-update-icon-cache -q -f "$DATA_HOME/icons/hicolor" 2>/dev/null || true
fi

# Metainfo (AppStream)
cat > "$METAINFO_FILE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>com.gekko.adb</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>MIT</project_license>
  <name>Gekko ADB Studio</name>
  <summary>Master Suite de control ADB para Linux</summary>
  <description>
    <p>Suite nativa GTK 3/GTK 4 que ejecuta comandos ADB con un clic:
       conexión, transferencias, instalación, boot, shell, ajustes, scrcpy y presets de debloat.</p>
  </description>
  <url type="homepage">https://github.com/The-Gekko/gekko-adb</url>
  <launchable type="desktop-id">com.gekko.adb.desktop</launchable>
  <categories>
    <category>Development</category>
    <category>System</category>
    <category>Utility</category>
  </categories>
</component>
EOF
ok "Metainfo: $METAINFO_FILE"

# Eliminar el launcher web legacy (GekkoADB.desktop)
if [[ -f "$LEGACY_DESKTOP_FILE" ]]; then
    rm -f "$LEGACY_DESKTOP_FILE"
    warn "Eliminado el launcher legacy (GekkoADB.desktop)."
fi

# Aislamiento de entorno para la app instalada (informativo; el launcher ya exporta la ruta)
cat > "$ENV_FILE" <<EOF
GEKKO_ADB_PROJECT_DIR="$INSTALL_DIR"
EOF

# Reglas udev para ADB (android-udev en Arch). Solo si se gestionan dependencias.
if $INSTALL_DEPS && [[ -f /usr/lib/udev/rules.d/51-android.rules && -x /usr/bin/udevadm ]]; then
    if sudo -n true 2>/dev/null; then
        sudo udevadm control --reload-rules 2>/dev/null || true
        sudo udevadm trigger 2>/dev/null || true
    else
        info "Para recargar las reglas udev sin reiniciar: sudo udevadm control --reload-rules && sudo udevadm trigger"
    fi
fi

ok "Instalación completada."
info "Inicia la app con: gekko-adb"
info "Ruta de instalación: $INSTALL_DIR"
info "Para desinstalar: $INSTALL_DIR/install.sh --uninstall"
