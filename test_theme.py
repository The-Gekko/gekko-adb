#!/usr/bin/env python3
"""Tests del tema (sin display)."""
import os
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix='gekko_theme_test_')
HOME_FAKE = Path(TMP) / 'home'
HOME_FAKE.mkdir()
os.environ['HOME'] = str(HOME_FAKE)
os.environ['XDG_CONFIG_HOME'] = str(HOME_FAKE / 'config')
os.environ['XDG_CACHE_HOME'] = str(HOME_FAKE / 'cache')
os.environ['GEKKO_ADB_BASE'] = str(Path(__file__).resolve().parent)

import gekko_adb_theme as theme  # noqa: E402


class TestTheme(unittest.TestCase):
    def test_css_por_tema(self):
        for nombre in ('system', 'dark', 'light', 'invalido'):
            css, fuente, resuelto = theme.get_theme_css(nombre)
            self.assertIsInstance(css, str)
            self.assertIn('.gekko-window', css)
            self.assertTrue(fuente)
            self.assertTrue(resuelto)
        css, fuente, resuelto = theme.get_theme_css('matugen')
        self.assertIsInstance(css, str)
        self.assertIn('.gekko-window', css)
        self.assertTrue(resuelto)

    def test_matugen_caida_sin_css(self):
        old = theme.find_matugen_css
        try:
            theme.find_matugen_css = lambda: None
            css, fuente, resuelto = theme.get_theme_css('matugen')
            self.assertIsNone(fuente)
            self.assertIn('nodisponible', resuelto)
        finally:
            theme.find_matugen_css = old

    def test_css_tiene_colores(self):
        css, _, _ = theme.get_theme_css('dark')
        self.assertIn('#', css)

    def test_estado_matugen(self):
        status = theme.get_matugen_status()
        self.assertIn('binario', status)
        self.assertIn('css', status)

    def test_monitor_solo_matugen(self):
        self.assertIsNone(theme.get_monitor_path('dark'))
        old = theme.find_matugen_css
        try:
            theme.find_matugen_css = lambda: Path(TMP) / 'matugen.css'
            self.assertEqual(theme.get_monitor_path('matugen'),
                             Path(TMP) / 'matugen.css')
        finally:
            theme.find_matugen_css = old


if __name__ == '__main__':
    unittest.main()
