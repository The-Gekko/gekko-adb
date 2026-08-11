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


def _parse_matugen_colors(path):
    colors = {}
    if not path:
        return colors
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            m = re.match(r'\s*@define-color\s+([\w-]+)\s+(#[0-9a-fA-F]{3,8})', line)
            if m:
                colors[m.group(1).lower()] = m.group(2)
    except Exception:
        pass
    return colors


def _system_prefers_dark():
    try:
        res = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.interface',
                              'color-scheme'], capture_output=True, text=True, timeout=10)
        if 'dark' in res.stdout.lower():
            return True
    except Exception:
        pass
    return True


def _render(palette):
    return _CSS_TEMPLATE.format(**palette)


def get_theme_css(theme):
    """Devuelve (css, fuente, resuelto).

    - system: dark/light según color-scheme del escritorio.
    - matugen: usa el CSS generado; si falta, cae a dark con
      resuelto='matugen:nodisponible' (la UI puede avisar).
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
            return _render(_DARK), None, 'matugen:nodisponible'
        colors = _parse_matugen_colors(css_path)
        palette = dict(_DARK)
        mapa = {
            'bg': ['base', 'bg0_hard', 'bg'],
            'sidebar': ['surface0', 'base', 'bg0'],
            'card': ['surface1', 'surface0', 'surface'],
            'hover': ['surface2', 'surface1'],
            'pressed': ['surface3', 'surface2'],
            'text': ['on_base', 'text', 'foreground'],
            'sub': ['on_surface_variant', 'surface2', 'text'],
            'primary': ['primary', 'accent', 'green'],
            'on_primary': ['on_primary', 'on_accent'],
            'warn': ['warning', 'orange', 'warn'],
            'error': ['error', 'red'],
            'blue': ['secondary', 'blue'],
            'border': ['surface2', 'surface1'],
        }
        for clave, candidatos in mapa.items():
            for cand in candidatos:
                if cand in colors:
                    palette[clave] = colors[cand]
                    break
        return _render(palette), str(css_path), 'matugen'
    return _render(_DARK), 'dark', 'dark'


def get_monitor_path(theme):
    """Ruta a vigilar con Gio.FileMonitor (solo matugen)."""
    if theme == 'matugen':
        return find_matugen_css()
    return None