#!/bin/bash
# Gekko ADB Studio - instalador Arch/Garuda (pacman) y Solus (eopkg).
# Instala en directorios XDG (nunca root, nunca rutas hardcodeadas de usuario).
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

# Detección de distribución (Arch/Garuda → pacman, Solus → eopkg)
DISTRO="unknown"
if [[ -r /etc/os-release ]]; then
    . /etc/os-release
    case "${ID:-}" in
        arch|garuda|manjaro) DISTRO="arch" ;;
        solus) DISTRO="solus" ;;
    esac
fi

REQUIRED_PACKAGES=(
    python
    python-gobject
    gtk3
    gtk4
    android-tools
    scrcpy
    glib2
    xdg-utils
)
OPTIONAL_PACKAGES=(matugen)

if [[ "$DISTRO" == "solus" ]]; then
    REQUIRED_PACKAGES=(
        python
        python-gobject
        libgtk-3
        libgtk-4
        android-tools
        scrcpy
        glib2
        xdg-utils
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

info()  { echo -e "${CYAN}[i]${RESET} $*"; }
ok()    { echo -e "${GREEN}[✓]${RESET} $*"; }
warn()  { echo -e "${YELLOW}[!]${RESET} $*"; }
fail()  { echo -e "${RED}[✗]${RESET} $*" >&2; }

usage() {
    cat <<EOF
Gekko ADB Studio - instalador Arch/Garuda (pacman) y Solus (eopkg)

Uso: ./install.sh [opciones]

Opciones:
  --check         Verificar el entorno sin escribir nada
  --uninstall     Eliminar la app (conserva config y logs)
  --no-deps       No instalar dependencias con el gestor de paquetes
  --assume-yes    Confirmar la instalación de dependencias automáticamente
  --help          Mostrar esta ayuda

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

if [[ "$DISTRO" == "unknown" ]]; then
    warn "Distribución no reconocida; asumo Arch (pacman)."
    DISTRO="arch"
fi

check_package() {
    if [[ "$DISTRO" == "solus" ]]; then
        eopkg info "$1" >/dev/null 2>&1
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

# ------------------------------------------------------------- desinstalar
if [[ "${DO_UNINSTALL:-false}" == "true" ]]; then
    info "Desinstalando Gekko ADB Studio…"
    for target in "${INTEGRATION_TARGETS[@]}"; do
        if [[ -e "$target" ]]; then
            rm -f "$target" && ok "Eliminado: $target"
        fi
    done
    if [[ -d "$INSTALL_DIR" ]]; then
        rm -rf "$INSTALL_DIR" && ok "Eliminado: $INSTALL_DIR"
    fi
    if [[ -d "$APP_DATA_ROOT" ]] && ! ls "$APP_DATA_ROOT" >/dev/null 2>&1; then
        rmdir "$APP_DATA_ROOT" 2>/dev/null || true
    fi
    info "Config, logs y presets se conservan en $CONFIG_HOME/gekko-adb y $LOG_DIR."
    ok "Desinstalación completada."
    exit 0
fi

# ------------------------------------------------------------- instalación
info "Instalando en $INSTALL_DIR…"
mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$APP_DIR" "$ICON_DIR" "$METAINFO_DIR" "$LOG_DIR"

BACKUP_DIR=""
if [[ -d "$INSTALL_DIR" && -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
    BACKUP_DIR="${APP_DATA_ROOT}/app.bak.$(date +%s)"
    mv "$INSTALL_DIR" "$BACKUP_DIR"
    warn "Backup de versión anterior: $BACKUP_DIR"
fi

install_core() {
    mkdir -p "$INSTALL_DIR"
    cp "$SCRIPT_DIR/gekko_adb_core.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/gekko_adb_theme.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/gekko-adb-gtk4.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/gekko-adb-gtk3.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/adb_commands.json" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/debloat_presets.json" "$INSTALL_DIR/"
    mkdir -p "$INSTALL_DIR/bin" "$INSTALL_DIR/assets"
    cp "$SCRIPT_DIR/bin/gekko-adb" "$INSTALL_DIR/bin/gekko-adb"
    cp "$SCRIPT_DIR/assets/gekko-adb.png" "$INSTALL_DIR/assets/gekko-adb.png"
    cp "$SCRIPT_DIR/assets/gekko-adb-512.png" "$INSTALL_DIR/assets/gekko-adb-512.png"
    chmod +x "$INSTALL_DIR/bin/gekko-adb"
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

# Desktop entry (nuevo ID com.gekko.adb)
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Gekko ADB Studio
Comment=Master Suite de control ADB para Linux (GTK 3/4)
Exec=$BIN_DIR/gekko-adb
Icon=gekko-adb
Terminal=false
Categories=Development;System;Utility;
Keywords=ADB;Android;Debloat;Samsung;Scrcpy;Gekko;
StartupWMClass=com.gekko.adb
EOF
ok "Desktop entry: $DESKTOP_FILE"

# Icono
cp "$SCRIPT_DIR/assets/gekko-adb-512.png" "$ICON_FILE"
ok "Ícono: $ICON_FILE"

# Refrescar caché de íconos hicolor
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -f "$DATA_HOME/icons/hicolor" 2>/dev/null || true
fi

# Metainfo
cat > "$METAINFO_FILE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>com.gekko.adb</id>
  <name>Gekko ADB Studio</name>
  <summary>Master Suite de control ADB para Linux</summary>
  <description>
    <p>Suite nativa GTK 3/GTK 4 que ejecuta todos los comandos ADB con un clic:
       conexión, transferencias, instalación, boot, shell, ajustes, scrcpy y presets de debloat.</p>
  </description>
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

# Aislamiento de entorno para la app instalada
cat > "$ENV_FILE" <<EOF
GEKKO_ADB_PROJECT_DIR="$INSTALL_DIR"
EOF

# Post-install de udev para ADB (android-tools ya lo instala; refresco por si acaso)
if [[ -f /usr/lib/udev/rules.d/51-android.rules && -x /usr/bin/udevadm ]]; then
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger 2>/dev/null || true
fi

ok "Instalación completada."
info "Inicia la app con: gekko-adb"
info "Ruta de instalación: $INSTALL_DIR"
info "Para desinstalar: $0 --uninstall"
