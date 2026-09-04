#!/usr/bin/env python3
"""Gekko ADB Studio - temas GTK.

CSS compartido por los frontends GTK 3 y GTK 4. Sin `gi`: solo
pathlib/subprocess, para que los tests corran sin display.

Modos: system, dark, light, matugen. Matugen consume el CSS generado
(candidatos estilo Music-Gekko) y nunca toca la configuración global del WM.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

THEMES = ('system', 'dark', 'light', 'matugen')

CONFIG_HOME = Path(os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config')))
CACHE_HOME = Path(os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')))

# Paletas por defecto (estilo de la web: #0c1018 / acento #00e676)
_DARK = {
    'bg': '#0c1018', 'sidebar': '#070a10', 'card': '#131a26',
    'hover': '#1a2332', 'pressed': '#223048',
    'text': '#f0f6fc', 'sub': '#8b949e', 'border': '#1d2733',
    'primary': '#00e676', 'on_primary': '#00140c',
    'warn': '#ff9100', 'error': '#ff1744', 'blue': '#4facfe',
}
_LIGHT = {
    'bg': '#f2f5f9', 'sidebar': '#ffffff', 'card': '#e9edf4',
    'hover': '#dfe5ee', 'pressed': '#d3dbe7',
    'text': '#0c1018', 'sub': '#57606a', 'border': '#d4dae4',
    'primary': '#00a65a', 'on_primary': '#ffffff',
    'warn': '#e07b00', 'error': '#d5002f', 'blue': '#2d7ff9',
}

_CSS_TEMPLATE = """
@define-color bg {bg};
@define-color sidebar {sidebar};
@define-color card {card};
@define-color hover {hover};
@define-color pressed {pressed};
@define-color text {text};
@define-color sub {sub};
@define-color border {border};
@define-color primary {primary};
@define-color on_primary {on_primary};
@define-color warn {warn};
@define-color error {error};
@define-color blue {blue};

window, .gekko-window {{
    background-color: @bg;
    color: @text;
}}

.gekko-sidebar {{
    background-color: @sidebar;
    border-right: 1px solid @border;
}}

.gekko-sidebar .gekko-brand {{
    padding: 12px;
}}

.gekko-sidebar .gekko-brand > label.brand-title {{
    font-weight: 800;
    font-size: 17px;
    color: @text;
    letter-spacing: 1px;
}}

.gekko-sidebar .gekko-brand > label.brand-sub {{
    font-size: 10px;
    color: @sub;
}}

.gekko-cat {{
    background-color: transparent;
    padding: 8px 10px;
    border-radius: 8px;
    color: @sub;
}}

.gekko-cat:hover {{
    background-color: @hover;
    color: @text;
}}

.gekko-cat:selected, .gekko-cat:checked {{
    background-color: @primary;
    color: @on_primary;
}}

.gekko-card {{
    background-color: @card;
    border: 1px solid @border;
    border-radius: 10px;
    padding: 10px;
    margin: 4px;
}}

.gekko-card label.card-title {{
    font-weight: 700;
    font-size: 13px;
    color: @text;
}}

.gekko-card label.card-desc {{
    font-size: 11px;
    color: @sub;
}}

button.cmd-btn {{
    background-color: @hover;
    color: @text;
    border: 1px solid @border;
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 600;
}}

button.cmd-btn:hover {{
    background-color: @pressed;
}}

button.peligro-btn {{
    background-color: @error;
    color: #ffffff;
    border: 1px solid @error;
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 700;
}}

button.peligro-btn:hover {{
    background-color: darker(@error);
}}

button.warn-btn {{
    background-color: @warn;
    color: #000000;
    border: 1px solid @warn;
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 700;
}}

button.blue-btn {{
    background-color: @blue;
    color: #ffffff;
    border: 1px solid @blue;
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 700;
}}

.console-title {{
    font-weight: 700;
    font-size: 12px;
    color: @sub;
}}

.big-title {{
    font-weight: 800;
    font-size: 19px;
    color: @text;
}}

.sub-title {{
    font-size: 11px;
    color: @sub;
}}

.mono, textview {{
    font-family: "JetBrains Mono", "Fira Code", monospace;
    font-size: 11px;
}}

textview {{
    background-color: @sidebar;
    color: @text;
    border: 1px solid @border;
    border-radius: 8px;
}}

textview text {{
    background-color: @sidebar;
    color: @text;
}}

entry {{
    background-color: @sidebar;
    color: @text;
    border: 1px solid @border;
    border-radius: 8px;
    padding: 5px 8px;
}}

entry:focus {{
    border-color: @primary;
}}

combobox {{
    background-color: @sidebar;
    color: @text;
    border-radius: 8px;
}}

.status-dot {{
    border-radius: 999px;
    min-width: 10px;
    min-height: 10px;
}}

.status-dot.conn {{
    background-color: @primary;
}}

.status-dot.disc {{
    background-color: @error;
}}

.status-pill {{
    background-color: @card;
    border: 1px solid @border;
    border-radius: 999px;
    padding: 4px 12px;
}}

.stat-badge {{
    background-color: @card;
    border: 1px solid @border;
    border-radius: 10px;
    padding: 8px 12px;
}}

.stat-badge label.badge-title {{
    font-size: 10px;
    color: @sub;
    font-weight: 600;
}}

.stat-badge label.badge-value {{
    font-size: 12px;
    color: @text;
    font-weight: 700;
}}

separator {{
    background-color: @border;
    min-height: 1px;
}}

scrolledwindow {{
    background-color: transparent;
}}

textview.console-view text {{
    background-color: @bg;
}}

.error-text {{
    color: @error;
    font-size: 12px;
}}
"""


def matugen_css_candidates():
    return [
        CONFIG_HOME / 'gekko-adb' / 'matugen.css',
        CACHE_HOME / 'matugen' / 'colors-gtk.css',
        CONFIG_HOME / 'matugen' / 'generated' / 'gekko-adb.css',
    ]


def find_matugen_css():
    for path in matugen_css_candidates():
        if path.is_file():
            return path
    return None


def get_matugen_status():
    status = {'binario': shutil.which('matugen') or '', 'css': '', 'version': ''}
    css = find_matugen_css()
    if css:
        status['css'] = str(css)
    if status['binario']:
        try:
            res = subprocess.run(['matugen', '--version'], capture_output=True,
                                 text=True, timeout=10)
            status['version'] = (res.stdout or res.stderr).strip()[:60]
        except Exception:
            pass
    return status


_DEFINE_RE = re.compile(r'\s*@define-color\s+([\w-]+)\s+(#[0-9a-fA-F]{3,8})')
_VAR_RE = re.compile(r'\s*--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})')


def _parse_matugen_colors(path):
    """Colores de un CSS de matugen: @define-color o variables --nombre.

    Se ignoran los bloques @media (p. ej. prefers-color-scheme: light) para
    que no pisen la paleta principal, y gana la primera definición.
    """
    colors = {}
    if not path:
        return colors
    try:
        depth = 0
        in_media = False
        media_depth = 0
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            stripped = line.strip()
            if stripped.startswith('@media'):
                in_media = True
                media_depth = depth
            m = _DEFINE_RE.match(line) or _VAR_RE.match(line)
            if m and not in_media:
                colors.setdefault(m.group(1).lower().replace('-', '_'), m.group(2))
            depth += line.count('{') - line.count('}')
            if in_media and depth <= media_depth:
                in_media = False
    except Exception:
        pass
    return colors


def _system_prefers_dark():
    """True si el escritorio prefiere oscuro. Sin gsettings, se asume oscuro."""
    try:
        res = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.interface',
                              'color-scheme'], capture_output=True, text=True, timeout=10,
                             stdin=subprocess.DEVNULL)
        if res.returncode == 0 and res.stdout.strip():
            return 'dark' in res.stdout.lower()
    except Exception:
        pass
    gtk_theme = os.environ.get('GTK_THEME', '')
    if gtk_theme:
        return 'dark' in gtk_theme.lower()
    return True


def _luminance(hex_color):
    h = hex_color.lstrip('#')
    if len(h) in (3, 4):
        h = ''.join(c * 2 for c in h[:3])
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return 0.0
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _render(palette):
    return _CSS_TEMPLATE.format(**palette)


# Nombres Material (colors.css estándar de matugen) primero; después los
# de tipo GTK/libadwaita (window_bg_color, accent_color...) y los de otros
# templates (base, surface0...).
_MATUGEN_MAP = {
    'bg': ['background', 'surface', 'base', 'bg0_hard', 'bg', 'window_bg_color', 'theme_bg_color', 'view_bg_color'],
    'sidebar': ['surface_container_low', 'surface_dim', 'surface0', 'base', 'bg0', 'sidebar_bg_color', 'window_bg_color'],
    'card': ['surface_container', 'surface_container_high', 'surface1', 'surface0', 'card_bg_color', 'popover_bg_color', 'dialog_bg_color'],
    'hover': ['surface_container_high', 'surface_container_highest', 'surface2', 'surface1', 'popover_bg_color', 'headerbar_bg_color'],
    'pressed': ['surface_container_highest', 'surface_bright', 'surface3', 'surface2', 'headerbar_bg_color', 'card_bg_color'],
    'text': ['on_background', 'on_surface', 'on_base', 'text', 'foreground', 'window_fg_color', 'theme_fg_color', 'view_fg_color'],
    'sub': ['on_surface_variant', 'outline', 'surface2', 'sidebar_fg_color', 'headerbar_fg_color'],
    'primary': ['primary', 'accent', 'green', 'accent_color', 'accent_bg_color', 'theme_selected_bg_color'],
    'on_primary': ['on_primary', 'on_accent', 'accent_fg_color'],
    'warn': ['warning', 'tertiary', 'orange', 'warn'],
    'error': ['error', 'red', 'destructive_color', 'destructive_bg_color'],
    'blue': ['secondary', 'blue'],
    'border': ['outline_variant', 'outline', 'surface2', 'surface1', 'sidebar_backdrop_color', 'card_bg_color'],
}


def get_theme_css(theme):
    """Devuelve (css, modo, fuente).

    - modo: 'light' o 'dark', la paleta realmente aplicada (para
      gtk-application-prefer-dark-theme).
    - fuente: de dónde salió: 'light', 'dark', 'system', 'matugen:<ruta>',
      'matugen:nodisponible' (sin CSS) o 'matugen:sincolores' (CSS sin
      colores reconocibles); la UI puede avisar.
    """
    if theme == 'light':
        return _render(_LIGHT), 'light', 'light'
    if theme == 'dark':
        return _render(_DARK), 'dark', 'dark'
    if theme == 'system':
        if _system_prefers_dark():
            return _render(_DARK), 'dark', 'system'
        return _render(_LIGHT), 'light', 'system'
    if theme == 'matugen':
        css_path = find_matugen_css()
        if css_path is None:
            return _render(_DARK), 'dark', 'matugen:nodisponible'
        colors = _parse_matugen_colors(css_path)
        if not colors:
            return _render(_DARK), 'dark', 'matugen:sincolores'
        bg = None
        for cand in _MATUGEN_MAP['bg']:
            if cand in colors:
                bg = colors[cand]
                break
        modo = 'light' if bg and _luminance(bg) > 0.5 else 'dark'
        palette = dict(_LIGHT if modo == 'light' else _DARK)
        for clave, candidatos in _MATUGEN_MAP.items():
            for cand in candidatos:
                if cand in colors:
                    palette[clave] = colors[cand]
                    break
        return _render(palette), modo, f'matugen:{css_path}'
    return _render(_DARK), 'dark', 'dark'


def get_monitor_path(theme):
    """Ruta a vigilar con Gio.FileMonitor (solo matugen).

    Si aún no existe ningún CSS se devuelve el primer candidato para que el
    monitor detecte su creación.
    """
    if theme == 'matugen':
        return find_matugen_css() or matugen_css_candidates()[0]
    return None