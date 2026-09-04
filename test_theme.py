#!/usr/bin/env python3
"""Tests del tema (sin display)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TMP = tempfile.mkdtemp(prefix='gekko_theme_test_')
HOME_FAKE = Path(TMP) / 'home'
HOME_FAKE.mkdir()
os.environ['HOME'] = str(HOME_FAKE)
os.environ['XDG_CONFIG_HOME'] = str(HOME_FAKE / 'config')
os.environ['XDG_CACHE_HOME'] = str(HOME_FAKE / 'cache')
os.environ['GEKKO_ADB_BASE'] = str(Path(__file__).resolve().parent)

import gekko_adb_theme as theme  # noqa: E402


class _R:
    def __init__(self, stdout, rc=0):
        self.stdout = stdout
        self.returncode = rc


class TestTheme(unittest.TestCase):
    def test_css_por_tema(self):
        for nombre in ('system', 'dark', 'light', 'invalido', 'matugen'):
            css, modo, fuente = theme.get_theme_css(nombre)
            self.assertIsInstance(css, str)
            self.assertIn('.gekko-window', css)
            self.assertIn(modo, ('light', 'dark'))
            self.assertTrue(fuente)

    def test_system_respeta_escritorio_claro(self):
        with mock.patch.object(theme.subprocess, 'run', return_value=_R("'default'\n")):
            css, modo, fuente = theme.get_theme_css('system')
        self.assertEqual((modo, fuente), ('light', 'system'))
        self.assertIn('@define-color bg #f2f5f9', css)
        with mock.patch.object(theme.subprocess, 'run', return_value=_R("'prefer-dark'\n")):
            self.assertEqual(theme.get_theme_css('system')[1], 'dark')
        with mock.patch.object(theme.subprocess, 'run', side_effect=FileNotFoundError):
            with mock.patch.dict(os.environ, {'GTK_THEME': 'Adwaita:light'}):
                self.assertEqual(theme.get_theme_css('system')[1], 'light')
            with mock.patch.dict(os.environ, {'GTK_THEME': ''}):
                self.assertEqual(theme.get_theme_css('system')[1], 'dark')

    def test_matugen_css_tipo_gtk(self):
        gtk_css = Path(TMP) / 'colors-gtk.css'
        gtk_css.write_text(
            '@define-color window_bg_color #1a1111;\n'
            '@define-color window_fg_color #f0dedd;\n'
            '@define-color sidebar_bg_color #231919;\n'
            '@define-color sidebar_fg_color #d7c1c0;\n'
            '@define-color card_bg_color #3d3232;\n'
            '@define-color accent_color #ffb3b1;\n'
            '@define-color accent_fg_color #571d1f;\n'
            '@define-color destructive_color #ffb4ab;\n',
            encoding='utf-8')
        with mock.patch.object(theme, 'find_matugen_css', return_value=gtk_css):
            css, modo, fuente = theme.get_theme_css('matugen')
        self.assertEqual(modo, 'dark')
        self.assertEqual(fuente, f'matugen:{gtk_css}')
        self.assertIn('@define-color bg #1a1111', css)
        self.assertIn('@define-color primary #ffb3b1', css)
        self.assertIn('@define-color on_primary #571d1f', css)
        self.assertIn('@define-color error #ffb4ab', css)

    def test_matugen_material_claro(self):
        mat = Path(TMP) / 'colors.css'
        mat.write_text(
            '@define-color background #fef7ff;\n'
            '@define-color on_background #1d1b20;\n'
            '@define-color surface #fef7ff;\n'
            '@define-color on_surface #1d1b20;\n'
            '@define-color surface_container #f3edf7;\n'
            '@define-color surface_container_high #ece6f0;\n'
            '@define-color surface_container_highest #e6e0e9;\n'
            '@define-color outline_variant #cac4d0;\n'
            '@define-color primary #6750a4;\n'
            '@define-color on_primary #ffffff;\n'
            '@define-color error #b3261e;\n'
            '@media (prefers-color-scheme: dark) {\n'
            '  @define-color background #141218;\n'
            '  @define-color on_background #e6e0e9;\n'
            '}\n', encoding='utf-8')
        with mock.patch.object(theme, 'find_matugen_css', return_value=mat):
            css, modo, fuente = theme.get_theme_css('matugen')
        self.assertEqual(modo, 'light')
        self.assertIn('@define-color bg #fef7ff', css)
        self.assertIn('@define-color text #1d1b20', css)
        self.assertIn('@define-color card #f3edf7', css)
        self.assertIn('@define-color border #cac4d0', css)

    def test_matugen_variables_root(self):
        var = Path(TMP) / 'vars.css'
        var.write_text(':root {\n  --window-bg-color: #101010;\n  --window-fg-color: #f0f0f0;\n  --accent-color: #00e676;\n}\n')
        colors = theme._parse_matugen_colors(var)
        self.assertEqual(colors['window_bg_color'], '#101010')
        self.assertEqual(colors['accent_color'], '#00e676')

    def test_matugen_sin_colores_y_sin_css(self):
        empty = Path(TMP) / 'empty.css'
        empty.write_text('/* nada */\n')
        with mock.patch.object(theme, 'find_matugen_css', return_value=empty):
            css, modo, fuente = theme.get_theme_css('matugen')
        self.assertEqual(fuente, 'matugen:sincolores')
        with mock.patch.object(theme, 'find_matugen_css', return_value=None):
            css, modo, fuente = theme.get_theme_css('matugen')
        self.assertEqual((modo, fuente), ('dark', 'matugen:nodisponible'))

    def test_luminancia(self):
        self.assertGreater(theme._luminance('#ffffff'), 0.9)
        self.assertLess(theme._luminance('#000'), 0.1)

    def test_estado_matugen(self):
        status = theme.get_matugen_status()
        self.assertIn('binario', status)
        self.assertIn('css', status)

    def test_monitor_matugen_aunque_no_exista(self):
        self.assertIsNone(theme.get_monitor_path('dark'))
        with mock.patch.object(theme, 'find_matugen_css', return_value=None):
            self.assertEqual(theme.get_monitor_path('matugen'), theme.matugen_css_candidates()[0])
        with mock.patch.object(theme, 'find_matugen_css', return_value=Path(TMP) / 'matugen.css'):
            self.assertEqual(theme.get_monitor_path('matugen'), Path(TMP) / 'matugen.css')


if __name__ == '__main__':
    unittest.main()
