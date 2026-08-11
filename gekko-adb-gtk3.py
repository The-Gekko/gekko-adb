#!/usr/bin/env python3
"""Gekko ADB Studio - frontend GTK 3 (compatibilidad).

API específica de GTK 3: pack_start/add/show_all, Gdk.Screen,
StyleContext.add_provider_for_screen. No importar el frontend GTK 4 aquí.
"""
from gi import require_version
require_version('Gtk', '3.0')
require_version('Gdk', '3.0')
from gi.repository import Gdk, Gio, GLib, Gtk

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gekko_adb_core import (
    APP_ID,
    APP_NAME,
    cargar_config,
    guardar_config,
    load_catalogo,
    preset_buttons,
    start_command,
)
from gekko_adb_theme import THEMES, get_theme_css, get_monitor_path

_PRIORITY = Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION


def css(widget, *classes):
    ctx = widget.get_style_context()
    for c in classes:
        ctx.add_class(c)


class GekkoAdbGtk3App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.config = cargar_config()
        self._catalogo = load_catalogo()
        self._theme = self.config.get('General', 'theme', fallback='system')
        self._provider = None
        self._monitor = None
        self._monitor_source = 0
        self._workers = set()
        self._dashboard_widgets = {}
        self._conn_pill_label = None
        self._conn_dot = None
        self._debloat_specs = preset_buttons()
        self.win = None

    def do_activate(self):
        win = self.props.active_window
        if win:
            win.present()
            return
        self.win = Gtk.ApplicationWindow(application=self)
        self.win.set_title(APP_NAME)
        self.win.set_default_size(1180, 760)
        self.win.set_size_request(920, 600)
        self._build_ui()
        self.win.show_all()
        self.win.present()
        self._apply_theme(self._theme)
        self._setup_theme_monitor()
        self._refresh_device()
        GLib.timeout_add_seconds(10, self._tick_refresh)

    def do_shutdown(self):
        if self._monitor:
            try:
                self._monitor.cancel()
            except Exception:
                pass
        Gtk.Application.do_shutdown(self)

    # ------------------------------------------------------------------- UI
    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        css(root, 'gekko-window')
        root.pack_start(self._build_header(), False, False, 0)
        root.pack_start(self._build_body(), True, True, 0)
        root.pack_start(self._build_console(), False, False, 0)
        self.win.add(root)

    def _build_header(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bar.set_margin_top(8)
        bar.set_margin_bottom(8)
        bar.set_margin_start(12)
        bar.set_margin_end(12)

        pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        css(pill, 'status-pill')
        self._conn_dot = Gtk.Box()
        css(self._conn_dot, 'status-dot', 'disc')
        self._conn_dot.set_size_request(10, 10)
        self._conn_pill_label = Gtk.Label(label='Sin dispositivo')
        css(self._conn_pill_label, 'mono')
        pill.pack_start(self._conn_dot, False, False, 0)
        pill.pack_start(self._conn_pill_label, False, False, 0)
        bar.pack_start(pill, False, False, 0)

        refresh = Gtk.Button(label='🔄 Refrescar ADB')
        css(refresh, 'cmd-btn')
        refresh.connect('clicked', self._on_refresh)
        bar.pack_start(refresh, False, False, 0)

        bar.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL),
                       False, False, 0)

        bar.pack_start(Gtk.Label(label='Tema:'), False, False, 0)
        combo = Gtk.ComboBoxText()
        for i, t in enumerate(THEMES):
            combo.append_text(t)
            if t == self._theme:
                combo.set_active(i)
        if combo.get_active() < 0:
            combo.set_active(0)
        combo.connect('changed', self._on_theme_changed)
        bar.pack_start(combo, False, False, 0)
        return bar

    def _build_body(self):
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        css(sidebar, 'gekko-sidebar')
        sidebar.set_size_request(240, -1)

        brand = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        css(brand, 'gekko-brand')
        title = Gtk.Label(label='⚡ GEKKO ADB', xalign=0)
        css(title, 'brand-title')
        sub = Gtk.Label(label='Master Suite · Linux Native', xalign=0)
        css(sub, 'brand-sub')
        brand.pack_start(title, False, False, 0)
        brand.pack_start(sub, False, False, 0)
        sidebar.pack_start(brand, False, False, 0)

        self._cat_list = Gtk.ListBox()
        self._cat_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._cat_list.connect('row-selected', self._on_category_selected)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(self._cat_list)
        scroller.set_vexpand(True)
        sidebar.pack_start(scroller, True, True, 0)

        body.pack_start(sidebar, False, False, 0)

        self._stack = Gtk.Stack()
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)
        body.pack_start(self._stack, True, True, 0)

        for i, cat in enumerate(self._catalogo['categorias']):
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=f"{cat.get('icono', '•')}  {cat['titulo']}", xalign=0)
            css(label, 'gekko-cat')
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            label.set_margin_start(6)
            label.set_margin_end(6)
            row.add(label)
            row.cat_id = cat['id']
            self._cat_list.add(row)
            self._stack.add_named(self._build_page(cat), cat['id'])

        self._cat_list.select_row(self._cat_list.get_row_at_index(0))
        return body

    def _build_page(self, cat):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        page.set_margin_start(16)
        page.set_margin_end(16)
        page.set_margin_top(12)
        page.set_margin_bottom(12)

        head = Gtk.Label(label=cat['titulo'], xalign=0)
        css(head, 'big-title')
        page.pack_start(head, False, False, 0)
        if cat.get('desc'):
            d = Gtk.Label(label=cat['desc'], xalign=0, wrap=True)
            css(d, 'sub-title')
            page.pack_start(d, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        if cat.get('especial') == 'dashboard':
            flow = self._build_dashboard()
        elif cat['id'] == 'debloat':
            flow = self._build_command_flow(self._debloat_specs)
        else:
            flow = self._build_command_flow(cat.get('comandos', []))
        scroll.add(flow)
        page.pack_start(scroll, True, True, 0)
        return page

    def _build_dashboard(self):
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(3)
        flow.set_homogeneous(False)
        flow.set_valign(Gtk.Align.START)
        self._dashboard_widgets = {}
        campos = [
            ('Modelo Dispositivo', 'model'),
            ('Android / ABI', 'android'),
            ('Batería / Temp / Salud', 'battery'),
            ('Estado de fábrica', 'secure'),
            ('Pantalla / DPI', 'display'),
            ('Navegación', 'nav_mode'),
            ('Launcher HOME', 'home_role'),
        ]
        for titulo, campo in campos:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            css(box, 'stat-badge')
            t = Gtk.Label(label=titulo, xalign=0)
            css(t, 'badge-title')
            v = Gtk.Label(label='…', xalign=0)
            css(v, 'badge-value')
            v.set_line_wrap(True)
            v.set_max_width_chars(28)
            box.pack_start(t, False, False, 0)
            box.pack_start(v, False, False, 0)
            flow.add(box)
            self._dashboard_widgets[campo] = v
        return flow

    def _build_command_flow(self, specs):
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(3)
        flow.set_min_children_per_line(2)
        flow.set_homogeneous(True)
        flow.set_valign(Gtk.Align.START)
        for spec in specs:
            flow.add(self._build_card(spec))
        return flow

    def _build_card(self, spec):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        css(card, 'gekko-card')

        titulo = Gtk.Label(label=spec.get('titulo', spec['id']), xalign=0, wrap=True)
        css(titulo, 'card-title')
        card.pack_start(titulo, False, False, 0)

        desc = Gtk.Label(label=spec.get('desc', ''), xalign=0, wrap=True)
        css(desc, 'card-desc')
        card.pack_start(desc, False, False, 0)

        btn = Gtk.Button(label='▶  Ejecutar')
        if spec.get('peligro'):
            css(btn, 'peligro-btn')
        elif spec.get('warn'):
            css(btn, 'warn-btn')
        else:
            css(btn, 'cmd-btn')
        btn.connect('clicked', self._on_command, spec)
        card.pack_start(btn, False, False, 0)
        return card

    # --------------------------------------------------------------- console
    def _build_console(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_bottom(10)
        box.set_size_request(-1, 200)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        t = Gtk.Label(label='📜 Registro de ejecución en tiempo real', xalign=0)
        css(t, 'console-title')
        t.set_hexpand(True)
        clear = Gtk.Button(label='Limpiar')
        css(clear, 'cmd-btn')
        clear.connect('clicked', self._on_clear_console)
        head.pack_start(t, True, True, 0)
        head.pack_start(clear, False, False, 0)
        box.pack_start(head, False, False, 0)

        self._console_buf = None
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        text = Gtk.TextView()
        text.set_editable(False)
        text.set_cursor_visible(False)
        text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        css(text, 'console-view')
        self._console_buf = text.get_buffer()
        self._console_buf.set_text('Gekko ADB Studio iniciado. Sistema listo.')
        scroll.add(text)
        box.pack_start(scroll, True, True, 0)

        term = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        prompt = Gtk.Label(label='adb >')
        css(prompt, 'mono')
        self._term_entry = Gtk.Entry()
        self._term_entry.set_hexpand(True)
        self._term_entry.set_placeholder_text(
            'shell getprop ro.product.model · también: devices, push, install…')
        self._term_entry.connect('activate', self._on_terminal_exec)
        run_btn = Gtk.Button(label='Ejecutar')
        css(run_btn, 'cmd-btn')
        run_btn.connect('clicked', self._on_terminal_exec)
        term.pack_start(prompt, False, False, 0)
        term.pack_start(self._term_entry, True, True, 0)
        term.pack_start(run_btn, False, False, 0)
        box.pack_start(term, False, False, 0)
        return box

    # ------------------------------------------------------------- handlers
    def _on_category_selected(self, listbox, row):
        if row is None:
            return
        cat_id = row.cat_id
        if cat_id:
            self._stack.set_visible_child_name(cat_id)

    def _on_refresh(self, _btn):
        self._log('Refrescando estado del dispositivo…')
        self._refresh_device()

    def _on_theme_changed(self, combo):
        idx = combo.get_active()
        if idx < 0:
            return
        self._theme = list(THEMES)[idx]
        self.config.set('General', 'theme', self._theme)
        guardar_config(self.config)
        self._apply_theme(self._theme)
        self._setup_theme_monitor()

    def _on_clear_console(self, _btn):
        self._console_buf.set_text('Consola limpiada.')

    def _on_terminal_exec(self, _widget):
        cmd = self._term_entry.get_text().strip()
        if not cmd:
            return
        self._log(f'Terminal: adb > {cmd}')
        spec = {'id': 'terminal', 'titulo': 'Terminal', 'desc': '',
                'accion': 'terminal'}
        self._run_spec(spec, {'command': cmd})
        self._term_entry.set_text('')

    # ------------------------------------------------------------- running
    def _log(self, msg, kind='info'):
        if self._console_buf is None:
            return
        end = self._console_buf.get_end_iter()
        self._console_buf.insert(end,
                                 f'\n[{datetime.datetime.now().strftime("%H:%M:%S")}] {msg}')

    def _run_spec(self, spec, valores=None, flags=None):
        if spec.get('confirmar'):
            self._confirm_dialog(spec, valores, flags)
            return
        self._log(f"Ejecutando: {spec.get('titulo', spec.get('id', ''))}")

        def _on_done(result):
            GLib.idle_add(self._on_worker_done, spec, result, worker)
            return None

        def _on_error(err):
            GLib.idle_add(self._on_worker_error, spec, err, worker)
            return None

        worker = start_command(spec, valores, flags, on_done=_on_done, on_error=_on_error)
        self._workers.add(worker)

    def _on_worker_done(self, spec, result, worker):
        self._workers.discard(worker)
        out = result.get('stdout', '')
        err = result.get('stderr', '')
        extra = result.get('path', '')
        if result.get('success'):
            self._log(f"✔ {spec.get('titulo', spec.get('id', ''))} — OK")
        else:
            self._log(f"✘ {spec.get('titulo', spec.get('id', ''))} — ERROR")
        if out:
            self._log(out)
        if err:
            self._log(err, kind='error')
        if extra:
            self._log(f'Archivo: {extra}')
        if spec.get('accion') in ('quick_pull', 'pull', 'install', 'install_multiple',
                                  'settings_put', 'nav_mode', 'anim_scale', 'density',
                                  'density_reset', 'wm_size', 'wm_size_reset'):
            self._refresh_device()
        return False

    def _on_worker_error(self, spec, error, worker):
        self._workers.discard(worker)
        self._log(f'✘ {spec.get("titulo", spec.get("id", ""))}: {error}')
        return False

    def _confirm_dialog(self, spec, valores, flags):
        dialog = Gtk.Dialog(title=f"¿Confirmar {spec.get('titulo', '')}?",
                            transient_for=self.win)
        dialog.set_modal(True)
        label = Gtk.Label(
            label=f"Esta acción puede ser destructiva:\n\n{spec.get('desc', '')}\n\n"
                  f"¿Seguro que deseas continuar?")
        label.set_line_wrap(True)
        label.set_margin_top(16)
        label.set_margin_bottom(16)
        label.set_margin_start(16)
        label.set_margin_end(16)
        content = dialog.get_content_area()
        content.add(label)
        dialog.add_button('Cancelar', Gtk.ResponseType.CANCEL)
        dialog.add_button('Ejecutar', Gtk.ResponseType.OK)
        dialog.connect('response', self._on_confirm_response, spec, valores, flags)
        dialog.show_all()
        dialog.present()

    def _on_confirm_response(self, dialog, response, spec, valores, flags):
        if response == Gtk.ResponseType.OK:
            self._run_spec(spec, valores, flags)
        dialog.destroy()

    def _on_command(self, _btn, spec):
        campos = spec.get('campos') or []
        if not campos:
            self._run_spec(spec)
            return
        self._campos_dialog(spec)

    def _campos_dialog(self, spec):
        campos = spec.get('campos') or []
        dialog = Gtk.Dialog(title=spec.get('titulo', 'Argumentos'),
                            transient_for=self.win)
        dialog.set_modal(True)
        content = dialog.get_content_area()
        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(8)
        grid.set_margin_top(12)
        grid.set_margin_bottom(12)
        grid.set_margin_start(12)
        grid.set_margin_end(12)
        widgets = {}
        checks = []
        row = 0
        for campo in campos:
            key = campo['clave']
            label = Gtk.Label(label=f"{campo['etiqueta']}:", xalign=0)
            grid.attach(label, 0, row, 1, 1)
            w = self._build_campo_widget(campo, dialog, widgets)
            grid.attach(w, 1, row, 1, 1)
            widgets[key] = w
            row += 1
        for opt in spec.get('opciones') or []:
            chk = Gtk.CheckButton(label=opt['etiqueta'])
            chk.set_active(bool(opt.get('defecto', False)))
            checks.append((opt, chk))
            grid.attach(chk, 1, row, 1, 1)
            row += 1
        content.add(grid)
        dialog.add_button('Cancelar', Gtk.ResponseType.CANCEL)
        dialog.add_button('Ejecutar', Gtk.ResponseType.OK)
        dialog.connect('response', self._on_campos_response, spec, widgets, checks)
        dialog.show_all()
        dialog.present()

    def _build_campo_widget(self, campo, dialog, widgets):
        tipo = campo.get('tipo', 'texto')
        defecto = str(campo.get('defecto', ''))
        if tipo == 'select':
            combo = Gtk.ComboBoxText()
            for i, op in enumerate(campo.get('opciones') or []):
                combo.append(op['valor'], op['etiqueta'])
                if op.get('valor') == defecto or (defecto == '' and i == 0):
                    combo.set_active(i)
            if combo.get_active() < 0 and combo.get_model():
                combo.set_active(0)
            return combo
        if tipo in ('archivo', 'archivos', 'carpeta'):
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            entry = Gtk.Entry()
            entry.set_text(defecto)
            entry.set_hexpand(True)
            btn = Gtk.Button(label='Buscar…')
            css(btn, 'cmd-btn')
            btn.connect('clicked', self._on_file_pick, entry, tipo, dialog)
            box.pack_start(entry, True, True, 0)
            box.pack_start(btn, False, False, 0)
            return box
        entry = Gtk.Entry()
        entry.set_text(defecto)
        if tipo == 'paquete':
            btn = Gtk.Button(label='Lista…')
            css(btn, 'cmd-btn')
            btn.connect('clicked', self._on_package_pick, entry, dialog)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.pack_start(entry, True, True, 0)
            box.pack_start(btn, False, False, 0)
            return box
        return entry

    def _on_file_pick(self, _btn, entry, tipo, dialog):
        native = Gtk.FileChooserNative(title='Seleccionar',
                                       transient_for=dialog,
                                       action=Gtk.FileChooserAction.OPEN)
        if tipo == 'carpeta':
            native.set_action(Gtk.FileChooserAction.SELECT_FOLDER)
        if tipo == 'archivos':
            native.set_select_multiple(True)
        native.connect('response', self._on_file_pick_response, entry, tipo)
        native.show()
        native.run()
        native.destroy()

    def _on_file_pick_response(self, native, response, entry, tipo):
        if response == Gtk.ResponseType.ACCEPT:
            if tipo == 'archivos':
                paths = [f.get_path() for f in native.get_files()]
                entry.set_text('\n'.join(paths))
            else:
                entry.set_text(native.get_file().get_path())

    def _on_package_pick(self, _btn, entry, dialog):
        self._log('Cargando lista de paquetes…')

        def _on_done(result):
            GLib.idle_add(self._show_package_dialog, entry, result)
            return None

        def _on_error(err):
            GLib.idle_add(self._log, f'Error cargando paquetes: {err}')
            return None

        worker = start_command(
            {'id': 'pkg', 'titulo': 'paquetes', 'desc': '', 'accion': 'list_packages'},
            None, None, on_done=_on_done, on_error=_on_error)
        self._workers.add(worker)

    def _show_package_dialog(self, entry, result):
        pkgs = result.get('stdout', '').splitlines()
        dialog = Gtk.Dialog(title='Seleccionar paquete', transient_for=self.win)
        dialog.set_modal(True)
        dialog.set_default_size(520, 480)
        content = dialog.get_content_area()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        search = Gtk.SearchEntry()
        search.set_placeholder_text('Filtrar paquete…')
        box.pack_start(search, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        lst = Gtk.ListBox()
        self._pkg_items = []
        for p in pkgs:
            r = Gtk.ListBoxRow()
            lbl = Gtk.Label(label=p, xalign=0)
            r.add(lbl)
            lst.add(r)
            self._pkg_items.append(r)
        search.connect('search-changed', self._filter_packages, lst)
        lst.connect('row-activated', self._on_pkg_selected, entry, dialog)
        scroll.add(lst)
        box.pack_start(scroll, True, True, 0)
        content.add(box)
        dialog.add_button('Cerrar', Gtk.ResponseType.CANCEL)
        dialog.connect('response', lambda d, r: d.destroy())
        dialog.show_all()
        dialog.present()

    def _filter_packages(self, search, lst):
        query = search.get_text().lower()
        for row in self._pkg_items:
            lbl = row.get_child()
            row.set_visible(not query or query in lbl.get_text().lower())

    def _on_pkg_selected(self, _lst, row, entry, dialog):
        lbl = row.get_child()
        entry.set_text(lbl.get_text())
        dialog.destroy()

    def _on_campos_response(self, dialog, response, spec, widgets, checks):
        if response == Gtk.ResponseType.OK:
            valores = {}
            for key, w in widgets.items():
                if isinstance(w, Gtk.ComboBoxText):
                    valores[key] = w.get_active_id() or ''
                elif isinstance(w, Gtk.Box):
                    entry = w.get_children()[0]
                    valores[key] = entry.get_text().strip()
                else:
                    valores[key] = w.get_text().strip()
            flags = [opt['flag'] for opt, chk in checks if chk.get_active()]
            self._run_spec(spec, valores, flags)
        dialog.destroy()

    # ------------------------------------------------------------ device info
    def _refresh_device(self):
        def done(info):
            if info.get('connected'):
                css(self._conn_dot, 'status-dot', 'conn')
                self._conn_dot.get_style_context().remove_class('disc')
                self._conn_pill_label.set_text(
                    f"{info['model']} ({info['serial']})  ·  {info['battery']} "
                    f"·  {info['display']} @ {info['density']}")
                upd = self._dashboard_widgets
                upd['model'].set_text(info['model'])
                upd['android'].set_text(f"{info['android']} [{info['abi']}]")
                upd['battery'].set_text(f"{info['battery']} | {info['temperature']} "
                                        f"| {info['voltage']} ({info['health']})")
                upd['secure'].set_text(info['secure'])
                upd['display'].set_text(f"{info['display']} @ {info['density']}")
                upd['nav_mode'].set_text(info['nav_mode'])
                upd['home_role'].set_text(info['home_role'] or 'No asignado')
            else:
                css(self._conn_dot, 'status-dot', 'disc')
                self._conn_dot.get_style_context().remove_class('conn')
                self._conn_pill_label.set_text('Sin dispositivo · esperando ADB')
                for w in self._dashboard_widgets.values():
                    w.set_text('N/A')
            return False

        def _on_done(result):
            GLib.idle_add(done, self._info_from_result(result))
            return None

        def _on_error(err):
            GLib.idle_add(done, {'connected': False})
            return None

        worker = start_command(
            {'id': 'info', 'titulo': 'info', 'desc': '', 'accion': 'device_info'},
            None, None, on_done=_on_done, on_error=_on_error)
        self._workers.add(worker)

    def _info_from_result(self, result):
        if not result.get('success'):
            return {'connected': False}
        info = {'connected': True, 'serial': ''}
        for line in result['stdout'].splitlines():
            if ': ' in line:
                k, v = line.split(': ', 1)
                info[k.strip()] = v.strip()
        return info

    def _tick_refresh(self):
        self._refresh_device()
        return True

    # ----------------------------------------------------------------- theme
    def _apply_theme(self, theme):
        screen = Gdk.Screen.get_default()
        if screen is None:
            return
        css_text, _fuente, resolved = get_theme_css(theme)
        provider = Gtk.CssProvider()
        try:
            if hasattr(provider, 'load_from_data'):
                provider.load_from_data(css_text.encode())
            else:
                provider.load_from_string(css_text)
        except Exception:
            return
        if self._provider:
            try:
                Gtk.StyleContext.remove_provider_for_screen(screen, self._provider)
            except Exception:
                pass
        Gtk.StyleContext.add_provider_for_screen(screen, provider, _PRIORITY)
        self._provider = provider
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property('gtk-application-prefer-dark-theme',
                                  not (theme == 'light' or
                                       (theme == 'system' and resolved == 'light')))

    def _setup_theme_monitor(self):
        if self._monitor:
            try:
                self._monitor.cancel()
            except Exception:
                pass
            self._monitor = None
        if self._monitor_source:
            GLib.source_remove(self._monitor_source)
            self._monitor_source = 0
        path = get_monitor_path(self._theme)
        if path is None:
            return
        try:
            gfile = Gio.File.new_for_path(str(path))
            self._monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self._monitor.connect('changed', self._on_matugen_changed)
        except Exception:
            self._monitor = None

    def _on_matugen_changed(self, *_args):
        if self._monitor_source:
            GLib.source_remove(self._monitor_source)
        self._monitor_source = GLib.timeout_add(350, self._matugen_reload)

    def _matugen_reload(self):
        self._monitor_source = 0
        self._apply_theme(self._theme)
        return False


def main():
    app = GekkoAdbGtk3App()
    app.run(sys.argv)


if __name__ == '__main__':
    main()