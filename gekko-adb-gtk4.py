#!/usr/bin/env python3
"""Gekko ADB Studio - frontend GTK 4.

API específica de GTK 4: Gtk.Box.append, Gtk.Widget.set_child, Gdk.Display,
Gtk.FileDialog async, Gtk.DropDown. No importar aquí el frontend GTK 3 ni
cargar ambos toolkits en el mismo proceso.
"""
from gi import require_version
require_version('Gtk', '4.0')
require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gekko_adb_core import (
    APP_ID,
    APP_NAME,
    APP_VERSION,
    AUTO_CONECTAR,
    AutoArranque,
    CatalogoError,
    CommandWorker,
    cargar_config,
    guardar_config,
    compatibilidad,
    es_lectura,
    load_catalogo,
    necesita_confirmacion,
    preset_buttons,
    validar_campos,
    build_valores,
    spec_auto_conectar,
)
from gekko_adb_theme import THEMES, get_theme_css, get_monitor_path

_PRIORITY = Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION

# Acciones tras las que el dashboard puede haber cambiado.
_REFRESH_AFTER = {
    'role_set', 'pm_action', 'uninstall', 'restore', 'debloat_preset', 'restore_preset',
    'reboot', 'soft_reboot', 'nav_mode', 'anim_scale', 'density', 'density_reset',
    'wm_size', 'wm_size_reset', 'settings_put', 'settings_delete', 'rotation',
    'connect', 'disconnect', 'tcpip', 'usb', 'start_server', 'pair', 'reconnect',
    'wait_for_device', 'root', 'unroot', 'overlay_enable', 'overlay_disable',
}
_APK_KEYS = ('apk', 'apks', 'ota')


class GekkoAdbGtk4App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.config = cargar_config()
        self._theme = self.config.get('General', 'theme', fallback='system')
        self._auto_modo = self.config.get('General', 'auto_conectar', fallback='')
        if self._auto_modo not in AUTO_CONECTAR:
            self._auto_modo = ''
        self._auto = AutoArranque()
        self._auto_source = 0
        self._auto_sondeando = False
        self._auto_conectado = False
        self._provider = None
        self._monitor = None
        self._monitor_source = 0
        self._workers = set()
        # Worker al que apunta el botón Cancelar (None = nada largo en curso).
        self._cancelando = None
        self._cancel_btn = None
        self._file_dialogs = set()
        self._dashboard_widgets = {}
        self._conn_pill_label = None
        self._conn_dot = None
        self._console_buf = None
        self._console_view = None
        self._end_mark = None
        self._term_entry = None
        self._refreshing = False
        self._poll_paused = False
        self._theme_warned = False
        self._pending_logs = []
        self._load_error = None
        self.win = None
        try:
            self._catalogo = load_catalogo()
            self._debloat_specs = preset_buttons()
        except CatalogoError as e:
            self._load_error = str(e)
            self._catalogo = {'categorias': []}
            self._debloat_specs = []

    # ------------------------------------------------------------------ main
    def do_activate(self):
        win = self.props.active_window
        if win:
            win.present()
            return
        if self._load_error:
            self._fatal(self._load_error)
            return
        try:
            self.win = Gtk.ApplicationWindow(application=self)
            self.win.set_title(APP_NAME)
            self.win.set_default_size(1180, 760)
            self.win.set_size_request(920, 600)
            self._build_ui()
        except Exception as e:
            self._fatal(f'No se pudo construir la interfaz: {type(e).__name__}: {e}')
            return
        self.win.present()
        self._apply_theme(self._theme)
        self._setup_theme_monitor()
        self._refresh_device()
        GLib.timeout_add_seconds(10, self._tick_refresh)
        self._programar_auto()

    def _fatal(self, msg):
        print(f'ERROR: {msg}', file=sys.stderr)
        try:
            dlg = Gtk.MessageDialog(modal=True, message_type=Gtk.MessageType.ERROR,
                                    buttons=Gtk.ButtonsType.CLOSE, text=APP_NAME,
                                    secondary_text=msg)
            dlg.connect('response', lambda d, r: (d.destroy(), self.quit()))
            self.hold()
            dlg.present()
        except Exception:
            self.quit()

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
        root.set_css_classes(['gekko-window'])
        root.append(self._build_header())
        root.append(self._build_body())
        root.append(self._build_console())
        self.win.set_child(root)
        for msg in self._pending_logs:
            self._log(msg)
        self._pending_logs = []

    def _build_header(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bar.set_margin_top(8)
        bar.set_margin_bottom(8)
        bar.set_margin_start(12)
        bar.set_margin_end(12)

        pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        pill.set_css_classes(['status-pill'])
        self._conn_dot = Gtk.Box()
        self._conn_dot.set_css_classes(['status-dot', 'disc'])
        self._conn_dot.set_size_request(10, 10)
        self._conn_pill_label = Gtk.Label(label='Sin dispositivo')
        self._conn_pill_label.set_css_classes(['mono'])
        pill.append(self._conn_dot)
        pill.append(self._conn_pill_label)
        bar.append(pill)

        refresh = Gtk.Button(label='🔄 Refrescar ADB')
        refresh.set_css_classes(['cmd-btn'])
        refresh.connect('clicked', self._on_refresh)
        bar.append(refresh)

        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        bar.append(Gtk.Label(label='Tema:'))
        combo = Gtk.DropDown.new_from_strings(list(THEMES))
        try:
            combo.set_selected(THEMES.index(self._theme))
        except ValueError:
            combo.set_selected(0)
        combo.connect('notify::selected-item', self._on_theme_changed)
        bar.append(combo)

        bar.append(Gtk.Label(label='Al conectar:'))
        auto = Gtk.DropDown.new_from_strings(list(AUTO_CONECTAR.values()))
        auto.set_selected(list(AUTO_CONECTAR).index(self._auto_modo))
        auto.set_tooltip_text('Abre Gaming o QtScrcpy en cuanto conectas el móvil, por USB o por Wi-Fi')
        auto.connect('notify::selected-item', self._on_auto_changed)
        bar.append(auto)

        version = Gtk.Label(label=f'v{APP_VERSION}')
        version.set_css_classes(['brand-sub'])
        version.set_hexpand(True)
        version.set_halign(Gtk.Align.END)
        bar.append(version)
        return bar

    def _build_body(self):
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body.set_vexpand(True)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.set_css_classes(['gekko-sidebar'])
        sidebar.set_size_request(240, -1)

        brand = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        brand.set_css_classes(['gekko-brand'])
        title = Gtk.Label(label='⚡ GEKKO ADB')
        title.set_css_classes(['brand-title'])
        title.set_halign(Gtk.Align.START)
        sub = Gtk.Label(label='Master Suite · Linux Native')
        sub.set_css_classes(['brand-sub'])
        sub.set_halign(Gtk.Align.START)
        brand.append(title)
        brand.append(sub)
        sidebar.append(brand)

        self._cat_list = Gtk.ListBox()
        self._cat_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._cat_list.connect('row-selected', self._on_category_selected)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self._cat_list)
        scroller.set_vexpand(True)
        sidebar.append(scroller)
        body.append(sidebar)

        self._stack = Gtk.Stack()
        self._stack.set_hexpand(True)
        self._stack.set_vexpand(True)
        body.append(self._stack)

        for cat in self._catalogo['categorias']:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=f"{cat.get('icono', '•')}  {cat.get('titulo') or cat.get('id', '?')}",
                              xalign=0)
            label.set_css_classes(['gekko-cat'])
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            label.set_margin_start(6)
            label.set_margin_end(6)
            row.set_child(label)
            row.cat_id = cat.get('id', '')
            self._cat_list.append(row)
            self._stack.add_named(self._build_page(cat), cat.get('id', ''))

        first = self._cat_list.get_row_at_index(0)
        if first is not None:
            self._cat_list.select_row(first)
        return body

    def _build_page(self, cat):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        page.set_margin_start(16)
        page.set_margin_end(16)
        page.set_margin_top(12)
        page.set_margin_bottom(12)

        head = Gtk.Label(label=cat.get('titulo') or cat.get('id', '?'), xalign=0)
        head.set_css_classes(['big-title'])
        page.append(head)
        if cat.get('desc'):
            d = Gtk.Label(label=cat['desc'], xalign=0, wrap=True)
            d.set_css_classes(['sub-title'])
            page.append(d)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        if cat.get('especial') == 'dashboard':
            flow = self._build_dashboard()
        elif cat.get('id') == 'debloat':
            flow = self._build_command_flow(self._debloat_specs)
        else:
            flow = self._build_command_flow(cat.get('comandos', []))
        flow.set_vexpand(True)
        scroll.set_child(flow)
        page.append(scroll)
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
            ('SMS / Teléfono', 'sms_dialer'),
        ]
        for titulo, campo in campos:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_css_classes(['stat-badge'])
            t = Gtk.Label(label=titulo, xalign=0)
            t.set_css_classes(['badge-title'])
            v = Gtk.Label(label='…', xalign=0)
            v.set_css_classes(['badge-value'])
            v.set_wrap(True)
            v.set_max_width_chars(28)
            box.append(t)
            box.append(v)
            flow.append(box)
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
            flow.append(self._build_card(spec))
        return flow

    def _build_card(self, spec):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.set_css_classes(['gekko-card'])

        titulo = Gtk.Label(label=spec.get('titulo') or spec.get('id', '?'), xalign=0, wrap=True)
        titulo.set_css_classes(['card-title'])
        card.append(titulo)

        desc = Gtk.Label(label=spec.get('desc', ''), xalign=0, wrap=True)
        desc.set_css_classes(['card-desc'])
        card.append(desc)

        # El diálogo de confirmación solo aparece con 'confirmar': sin esta
        # etiqueta, la advertencia de un botón no destructivo no se vería nunca.
        if spec.get('advertencia'):
            aviso = Gtk.Label(label=f"⚠ {spec['advertencia']}", xalign=0, wrap=True)
            aviso.set_css_classes(['card-warn'])
            # El FlowBox es homogéneo: sin acotar, la advertencia más larga de la
            # categoría estiraría TODAS las tarjetas. Se ven dos líneas y el texto
            # íntegro queda en el tooltip y en el diálogo de confirmación.
            aviso.set_max_width_chars(40)
            aviso.set_lines(2)
            aviso.set_ellipsize(Pango.EllipsizeMode.END)
            aviso.set_tooltip_text(spec['advertencia'])
            card.append(aviso)

        if spec.get('especial') == 'terminal':
            btn = Gtk.Button(label='⌨  Ir a la consola')
            btn.set_css_classes(['cmd-btn'])
            btn.connect('clicked', self._on_focus_terminal)
        else:
            btn = Gtk.Button(label='▶  Ejecutar')
            if spec.get('peligro'):
                btn.set_css_classes(['peligro-btn'])
            elif not es_lectura(spec):
                # Naranja para todo lo que cambia algo en el móvil sin ser
                # destructivo: antes esta rama miraba una clave 'warn' que no
                # usaba ningún comando, así que el estilo estaba muerto.
                btn.set_css_classes(['warn-btn'])
            else:
                btn.set_css_classes(['cmd-btn'])
            btn.connect('clicked', self._on_command, spec)
            self._marcar_compatibilidad(card, btn, spec)
        card.append(btn)
        return card

    def _marcar_compatibilidad(self, card, btn, spec):
        """Atenúa el botón y explica por qué si el móvil conectado no lo admite.

        Sin dispositivo no se marca nada: un aviso en falso es peor que ninguno,
        porque el usuario deja de hacer caso a los avisos.
        """
        ok, motivo = compatibilidad(spec, getattr(self, '_device_info', None))
        card.gekko_spec = spec
        card.gekko_btn = btn
        btn.set_sensitive(ok)
        if not ok and motivo:
            btn.set_tooltip_text(motivo)
            card.set_tooltip_text(motivo)

    # --------------------------------------------------------------- console
    def _build_console(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_bottom(10)
        box.set_size_request(-1, 200)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        t = Gtk.Label(label='📜 Registro de ejecución en tiempo real', xalign=0)
        t.set_css_classes(['console-title'])
        t.set_hexpand(True)
        # Buscar y guardar: por aquí pasan salidas de miles de líneas
        # ('dumpsys batterystats', 'service list', 'settings list') y sin esto
        # el panel solo servía para mirarlas pasar.
        self._buscar_entry = Gtk.Entry()
        self._buscar_entry.set_placeholder_text('Buscar en el registro…')
        self._buscar_entry.set_width_chars(22)
        self._buscar_entry.connect('activate', self._on_buscar)
        cancel = Gtk.Button(label='⛔ Cancelar')
        cancel.set_css_classes(['peligro-btn'])
        cancel.connect('clicked', self._on_cancelar)
        # Oculto por defecto: los comandos duran milisegundos y un botón
        # parpadeando en cada clic sería peor que no tenerlo. Solo aparece
        # cuando uno se alarga (ver _vigilar_lento).
        cancel.set_visible(False)
        self._cancel_btn = cancel
        buscar_btn = Gtk.Button(label='Buscar')
        buscar_btn.set_css_classes(['cmd-btn'])
        buscar_btn.connect('clicked', self._on_buscar)
        guardar = Gtk.Button(label='Guardar…')
        guardar.set_css_classes(['cmd-btn'])
        guardar.connect('clicked', self._on_guardar_consola)
        clear = Gtk.Button(label='Limpiar')
        clear.set_css_classes(['cmd-btn'])
        clear.connect('clicked', self._on_clear_console)
        head.append(t)
        head.append(cancel)
        head.append(self._buscar_entry)
        head.append(buscar_btn)
        head.append(guardar)
        head.append(clear)
        box.append(head)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        text = Gtk.TextView()
        text.set_editable(False)
        text.set_cursor_visible(False)
        text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text.add_css_class('console-view')
        self._console_view = text
        self._console_buf = text.get_buffer()
        self._console_buf.set_text('Gekko ADB Studio iniciado. Sistema listo.')
        self._end_mark = self._console_buf.create_mark('gekko-end', self._console_buf.get_end_iter(), False)
        scroll.set_child(text)
        box.append(scroll)

        term = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        prompt = Gtk.Label(label='adb >')
        prompt.set_css_classes(['mono'])
        self._term_entry = Gtk.Entry()
        self._term_entry.set_hexpand(True)
        self._term_entry.set_placeholder_text(
            'shell getprop ro.product.model · también: devices, pull, install… (acepta comillas)')
        self._term_entry.connect('activate', self._on_terminal_exec)
        run_btn = Gtk.Button(label='Ejecutar')
        run_btn.set_css_classes(['cmd-btn'])
        run_btn.connect('clicked', self._on_terminal_exec)
        term.append(prompt)
        term.append(self._term_entry)
        term.append(run_btn)
        box.append(term)
        return box

    # ------------------------------------------------------------- handlers
    def _on_category_selected(self, listbox, row):
        if row is None:
            return
        cat_id = getattr(row, 'cat_id', '')
        if cat_id:
            self._stack.set_visible_child_name(cat_id)

    def _on_refresh(self, _btn):
        self._poll_paused = False
        self._log('Refrescando estado del dispositivo…')
        self._refresh_device()

    def _on_focus_terminal(self, _btn):
        if self._term_entry is not None:
            self._term_entry.grab_focus()

    def _on_theme_changed(self, combo, _pspec):
        idx = combo.get_selected()
        if idx is None or idx < 0 or idx >= len(THEMES):
            return
        self._theme = list(THEMES)[idx]
        self.config.set('General', 'theme', self._theme)
        err = guardar_config(self.config)
        if err:
            self._log(f'No se pudo guardar la configuración: {err}')
        self._theme_warned = False
        self._apply_theme(self._theme)
        self._setup_theme_monitor()

    def _on_auto_changed(self, combo, _pspec):
        idx = combo.get_selected()
        if idx is None or idx < 0 or idx >= len(AUTO_CONECTAR):
            return
        self._auto_modo = list(AUTO_CONECTAR)[idx]
        self.config.set('General', 'auto_conectar', self._auto_modo)
        err = guardar_config(self.config)
        if err:
            self._log(f'No se pudo guardar la configuración: {err}')
        # Lo que ya está conectado al cambiar la opción no cuenta como «conectar».
        self._auto.armar(self._auto_conectado)
        self._programar_auto()
        if self._auto_modo:
            self._log(f'Al conectar el móvil: {AUTO_CONECTAR[self._auto_modo]}.')

    # Un comando normal dura milisegundos; solo los largos (recompilar una app,
    # bugreport, screenrecord, esperar dispositivo) merecen ofrecer cancelación.
    SEGUNDOS_PARA_OFRECER_CANCELAR = 2

    def _vigilar_lento(self, worker):
        """Enseña el botón Cancelar si el comando sigue vivo pasados unos segundos."""
        def _comprobar():
            if worker in self._workers and worker.is_alive():
                self._cancelando = worker
                self._cancel_btn.set_visible(True)
            return False
        GLib.timeout_add_seconds(self.SEGUNDOS_PARA_OFRECER_CANCELAR, _comprobar)

    def _ocultar_cancelar(self, worker):
        if self._cancelando is worker:
            self._cancelando = None
            self._cancel_btn.set_visible(False)

    def _on_cancelar(self, *_a):
        worker = self._cancelando
        if worker is None:
            return
        self._log('Cancelando el comando en curso…')
        worker.cancel()

    def _texto_consola(self):
        b = self._console_buf
        return b.get_text(b.get_start_iter(), b.get_end_iter(), False)

    def _on_buscar(self, *_a):
        """Va a la siguiente coincidencia y la deja seleccionada y a la vista.

        Busca desde la última posición encontrada, así pulsar repetidamente
        recorre todas las apariciones y vuelve al principio al acabar.
        """
        texto = self._buscar_entry.get_text().strip()
        if not texto:
            return
        buf = self._console_buf
        desde = buf.get_iter_at_mark(buf.get_insert())
        hit = desde.forward_search(texto, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
        if not hit:
            hit = buf.get_start_iter().forward_search(
                texto, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
        if not hit:
            self._log(f'Sin coincidencias de «{texto}» en el registro.')
            return
        ini, fin = hit
        buf.select_range(ini, fin)
        self._console_view.scroll_to_iter(ini, 0.1, False, 0, 0)

    def _on_guardar_consola(self, *_a):
        dlg = Gtk.FileDialog.new()
        dlg.set_title('Guardar el registro')
        dlg.set_initial_name(
            f'gekko-adb-{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
        dlg.save(self, None, self._on_guardar_listo)

    def _on_guardar_listo(self, dlg, res):
        try:
            gfile = dlg.save_finish(res)
        except Exception:
            return                      # el usuario canceló: no es un error
        if gfile is None:
            return
        try:
            with open(gfile.get_path(), 'w', encoding='utf-8') as f:
                f.write(self._texto_consola())
            self._log(f'Registro guardado en {gfile.get_path()}')
        except OSError as e:
            self._log(f'No se pudo guardar el registro: {e}')

    def _on_clear_console(self, _btn):
        self._console_buf.set_text('Consola limpiada.')

    def _on_terminal_exec(self, _widget):
        cmd = self._term_entry.get_text().strip()
        if not cmd:
            return
        self._log(f'Terminal: adb > {cmd}')
        spec = {'id': 'terminal', 'titulo': 'Consola', 'desc': '', 'accion': 'terminal'}
        self._run_spec(spec, {'command': cmd})
        self._term_entry.set_text('')

    # ------------------------------------------------------------- running
    def _log(self, msg, kind='info'):
        if self._console_buf is None:
            self._pending_logs.append(msg)
            return
        stamp = datetime.datetime.now().strftime('%H:%M:%S')
        prefix = '⚠ ' if kind == 'error' else ''
        self._console_buf.insert(self._console_buf.get_end_iter(), f'\n[{stamp}] {prefix}{msg}')
        try:
            self._console_buf.move_mark(self._end_mark, self._console_buf.get_end_iter())
            self._console_view.scroll_mark_onscreen(self._end_mark)
        except Exception:
            pass

    def _run_spec(self, spec, valores=None, flags=None):
        """Punto de entrada de la UI: pide confirmación si hace falta y lanza."""
        # El criterio lo pone el núcleo, no cada interfaz: así GTK3 y GTK4
        # preguntan exactamente en los mismos casos, y una acción crítica
        # confirma aunque el comando del catálogo se olvidara de pedirlo.
        if necesita_confirmacion(spec):
            self._confirm_dialog(spec, valores, flags)
            return
        self._launch(spec, valores, flags)

    def _launch(self, spec, valores=None, flags=None):
        """Lanza el worker sin volver a pedir confirmación."""
        self._log(f"Ejecutando: {spec.get('titulo') or spec.get('id', '')}")

        def _on_done(result):
            GLib.idle_add(self._on_worker_done, spec, result, worker)

        def _on_error(err):
            GLib.idle_add(self._on_worker_error, spec, err, worker)

        worker = CommandWorker(spec, valores, flags, on_done=_on_done, on_error=_on_error)
        self._workers.add(worker)
        worker.start()
        self._vigilar_lento(worker)
        return worker

    def _on_worker_done(self, spec, result, worker):
        self._workers.discard(worker)
        self._ocultar_cancelar(worker)
        out = result.get('stdout', '')
        err = result.get('stderr', '')
        extra = result.get('path', '')
        titulo = spec.get('titulo') or spec.get('id', '')
        if result.get('success'):
            self._log(f"✔ {titulo} — OK")
        else:
            self._log(f"✘ {titulo} — ERROR")
        if out:
            self._log(out)
        if err:
            self._log(err, kind='error')
        if extra and result.get('success'):
            self._log(f'Archivo: {extra}')
        accion = spec.get('accion')
        if accion == 'kill_server' and result.get('success'):
            self._poll_paused = True
            self._log('Sondeo del dispositivo pausado (pulsa "Refrescar ADB" o "Iniciar servidor" para reanudar).')
        elif accion in _REFRESH_AFTER:
            self._poll_paused = False
            self._refresh_device()
        return False

    def _on_worker_error(self, spec, error, worker):
        self._workers.discard(worker)
        self._ocultar_cancelar(worker)
        self._log(f'✘ {spec.get("titulo") or spec.get("id", "")}: {error}', kind='error')
        return False

    def _confirm_dialog(self, spec, valores, flags):
        dialog = Gtk.Dialog(title=f"¿Confirmar {spec.get('titulo', '')}?", transient_for=self.win)
        dialog.set_modal(True)
        texto = f"Esta acción puede ser destructiva:\n\n{spec.get('desc', '')}"
        if spec.get('advertencia'):
            texto += f"\n\n⚠ {spec['advertencia']}"
        texto += "\n\n¿Seguro que deseas continuar?"
        label = Gtk.Label(label=texto)
        label.set_wrap(True)
        label.set_max_width_chars(60)
        label.set_margin_top(16)
        label.set_margin_bottom(16)
        label.set_margin_start(16)
        label.set_margin_end(16)
        dialog.get_content_area().append(label)
        dialog.add_button('Cancelar', Gtk.ResponseType.CANCEL)
        dialog.add_button('Ejecutar', Gtk.ResponseType.OK)
        dialog.connect('response', self._on_confirm_response, spec, valores, flags)
        dialog.present()
        return dialog

    def _on_confirm_response(self, dialog, response, spec, valores, flags):
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self._launch(spec, valores, flags)
        else:
            self._log(f"Cancelado: {spec.get('titulo') or spec.get('id', '')}")

    def _on_command(self, _btn, spec):
        if spec.get('especial') == 'terminal':
            self._on_focus_terminal(None)
            return
        if not (spec.get('campos') or []):
            self._run_spec(spec)
            return
        self._campos_dialog(spec)

    def _campos_dialog(self, spec):
        campos = spec.get('campos') or []
        dialog = Gtk.Dialog(title=spec.get('titulo', 'Argumentos'), transient_for=self.win)
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
            etiqueta = campo.get('etiqueta', key) + ('' if campo.get('opcional') else ' *')
            label = Gtk.Label(label=f"{etiqueta}:", xalign=0)
            grid.attach(label, 0, row, 1, 1)
            w = self._build_campo_widget(campo, dialog)
            grid.attach(w, 1, row, 1, 1)
            widgets[key] = w
            row += 1
        for opt in spec.get('opciones') or []:
            chk = Gtk.CheckButton(label=opt['etiqueta'])
            chk.set_active(bool(opt.get('defecto', False)))
            checks.append((opt, chk))
            grid.attach(chk, 1, row, 1, 1)
            row += 1
        error_label = Gtk.Label(label='', xalign=0, wrap=True)
        error_label.set_css_classes(['error-text'])
        grid.attach(error_label, 0, row, 2, 1)
        content.append(grid)
        dialog.add_button('Cancelar', Gtk.ResponseType.CANCEL)
        dialog.add_button('Ejecutar', Gtk.ResponseType.OK)
        dialog.connect('response', self._on_campos_response, spec, widgets, checks, error_label)
        dialog.present()
        return dialog

    def _build_campo_widget(self, campo, dialog):
        tipo = campo.get('tipo', 'texto')
        defecto = str(campo.get('defecto', ''))
        key = campo.get('clave', '')
        if tipo == 'select':
            opciones = campo.get('opciones') or []
            combo = Gtk.DropDown.new_from_strings([op['etiqueta'] for op in opciones])
            combo.gekko_values = [op['valor'] for op in opciones]
            sel = 0
            for i, op in enumerate(opciones):
                if op.get('valor') == defecto:
                    sel = i
                    break
            combo.set_selected(sel)
            return combo
        if tipo in ('archivo', 'archivos', 'carpeta'):
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            entry = Gtk.Entry()
            entry.set_text(defecto)
            entry.set_hexpand(True)
            btn = Gtk.Button(label='Buscar…')
            btn.set_css_classes(['cmd-btn'])
            btn.connect('clicked', self._on_file_pick, entry, tipo, key, dialog)
            box.append(entry)
            box.append(btn)
            return box
        entry = Gtk.Entry()
        entry.set_text(defecto)
        if tipo == 'numero':
            entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        if tipo == 'paquete':
            btn = Gtk.Button(label='Lista…')
            btn.set_css_classes(['cmd-btn'])
            btn.connect('clicked', self._on_package_pick, entry, dialog)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            entry.set_hexpand(True)
            box.append(entry)
            box.append(btn)
            return box
        return entry

    def _on_file_pick(self, _btn, entry, tipo, key, parent):
        fdlg = Gtk.FileDialog.new()
        fdlg.set_title('Seleccionar archivos' if tipo == 'archivos' else 'Seleccionar')
        if tipo in ('archivo', 'archivos') and key in _APK_KEYS:
            apk = Gtk.FileFilter()
            apk.set_name('APK / OTA')
            for pat in ('*.apk', '*.zip', '*.ota', '*.apks'):
                apk.add_pattern(pat)
            allf = Gtk.FileFilter()
            allf.set_name('Todos los archivos')
            allf.add_pattern('*')
            store = Gio.ListStore.new(Gtk.FileFilter)
            store.append(apk)
            store.append(allf)
            fdlg.set_filters(store)
            fdlg.set_default_filter(apk)
        self._file_dialogs.add(fdlg)
        try:
            if tipo == 'archivos':
                fdlg.open_multiple(parent, None, self._on_pick_multiple, entry)
            elif tipo == 'carpeta':
                fdlg.select_folder(parent, None, self._on_pick_folder, entry)
            else:
                fdlg.open(parent, None, self._on_pick_single, entry)
        except Exception as e:
            self._file_dialogs.discard(fdlg)
            self._log(f'Error abriendo el selector: {e}', kind='error')

    def _set_path(self, entry, gfile):
        p = gfile.get_path() if gfile is not None else None
        if p:
            entry.set_text(p)
        else:
            self._log('Solo se admiten archivos locales', kind='error')

    def _on_pick_single(self, fdlg, result, entry):
        self._file_dialogs.discard(fdlg)
        try:
            f = fdlg.open_finish(result)
        except GLib.Error:
            return
        self._set_path(entry, f)

    def _on_pick_folder(self, fdlg, result, entry):
        self._file_dialogs.discard(fdlg)
        try:
            f = fdlg.select_folder_finish(result)
        except GLib.Error:
            return
        self._set_path(entry, f)

    def _on_pick_multiple(self, fdlg, result, entry):
        self._file_dialogs.discard(fdlg)
        try:
            files = fdlg.open_multiple_finish(result)
        except GLib.Error:
            return
        paths = []
        for i in range(files.get_n_items()):
            p = files.get_item(i).get_path()
            if p:
                paths.append(p)
        if not paths:
            self._log('Solo se admiten archivos locales', kind='error')
            return
        entry.set_text('\n'.join(paths))

    def _on_package_pick(self, btn, entry, dialog):
        self._log('Cargando lista de paquetes…')
        btn.set_sensitive(False)

        def _on_done(result):
            GLib.idle_add(self._show_package_dialog, entry, result, btn)

        def _on_error(err):
            GLib.idle_add(self._log, f'Error cargando paquetes: {err}', 'error')
            GLib.idle_add(btn.set_sensitive, True)

        worker = CommandWorker({'id': 'pkg', 'titulo': 'paquetes', 'desc': '', 'accion': 'list_packages'},
                               {'filtro': '-u'}, None, on_done=_on_done, on_error=_on_error)
        self._workers.add(worker)
        worker.start()

    def _show_package_dialog(self, entry, result, btn=None):
        if btn is not None:
            btn.set_sensitive(True)
        pkgs = result.get('packages') or []
        if not result.get('success'):
            self._log(f"No se pudo listar paquetes: {result.get('stderr') or result.get('stdout')}", kind='error')
            return False
        if not pkgs:
            self._log('El dispositivo no devolvió paquetes.', kind='error')
            return False
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
        box.append(search)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        lst = Gtk.ListBox()
        rows = []
        for p in pkgs:
            r = Gtk.ListBoxRow()
            r.set_child(Gtk.Label(label=p, xalign=0))
            lst.append(r)
            rows.append(r)
        search.connect('search-changed', self._filter_packages, rows)
        lst.connect('row-activated', self._on_pkg_selected, entry, dialog)
        scroll.set_child(lst)
        box.append(scroll)
        content.append(box)
        dialog.add_button('Cerrar', Gtk.ResponseType.CANCEL)
        dialog.connect('response', lambda d, r: d.destroy())
        dialog.present()
        return False

    def _filter_packages(self, search, rows):
        query = search.get_text().lower()
        for row in rows:
            row.set_visible(not query or query in row.get_child().get_text().lower())

    def _on_pkg_selected(self, _lst, row, entry, dialog):
        entry.set_text(row.get_child().get_text())
        dialog.destroy()

    def _widget_value(self, w):
        if isinstance(w, Gtk.DropDown):
            idx = w.get_selected()
            values = getattr(w, 'gekko_values', [])
            return values[idx] if 0 <= idx < len(values) else ''
        if isinstance(w, Gtk.Box):
            entry = w.get_first_child()
            return entry.get_text().strip()
        return w.get_text().strip()

    def _on_campos_response(self, dialog, response, spec, widgets, checks, error_label=None):
        if response != Gtk.ResponseType.OK:
            dialog.destroy()
            return
        valores = {key: self._widget_value(w) for key, w in widgets.items()}
        flags = [opt['flag'] for opt, chk in checks if chk.get_active()]
        errores = validar_campos(spec, build_valores(spec, valores, flags))
        if errores:
            if error_label is not None:
                error_label.set_text('\n'.join(errores))
            self._log('\n'.join(errores), kind='error')
            return
        dialog.destroy()
        self._run_spec(spec, valores, flags)

    # ------------------------------------------------------------ device info
    def _refresh_device(self):
        if self._refreshing:
            return
        self._refreshing = True

        def done(result):
            self._refreshing = False
            info = result.get('info') or {'connected': False, 'message': result.get('stderr', '')}
            upd = self._dashboard_widgets
            if info.get('connected'):
                self._conn_dot.set_css_classes(['status-dot', 'conn'])
                self._conn_pill_label.set_text(
                    f"{info['model']} ({info['serial']})  ·  {info['battery']} "
                    f"·  {info['display']} @ {info['density']}")
                upd['model'].set_text(info['model'])
                upd['android'].set_text(f"{info['android']} [{info['abi']}]")
                upd['battery'].set_text(f"{info['battery']} | {info['temperature']} "
                                        f"| {info['voltage']} ({info['health']})")
                upd['secure'].set_text(info['secure'])
                upd['display'].set_text(f"{info['display']} @ {info['density']}")
                upd['nav_mode'].set_text(info['nav_mode'])
                upd['home_role'].set_text(info['home_role'] or 'No asignado')
                if 'sms_dialer' in upd:
                    upd['sms_dialer'].set_text(f"{info.get('sms_role') or '—'} / {info.get('dialer_role') or '—'}")
            else:
                self._conn_dot.set_css_classes(['status-dot', 'disc'])
                msg = info.get('message') or 'Sin dispositivo · esperando ADB'
                self._conn_pill_label.set_text(msg if info.get('serial') else 'Sin dispositivo · esperando ADB')
                for w in upd.values():
                    w.set_text('N/A')
                if info.get('serial'):
                    upd['model'].set_text(msg)
            return False

        def _on_done(result):
            GLib.idle_add(done, result)
            GLib.idle_add(self._workers.discard, worker)

        def _on_error(err):
            GLib.idle_add(done, {'success': False, 'stderr': str(err)})
            GLib.idle_add(self._workers.discard, worker)

        worker = CommandWorker({'id': 'info', 'titulo': 'info', 'desc': '', 'accion': 'device_info'},
                               None, None, on_done=_on_done, on_error=_on_error)
        self._workers.add(worker)
        worker.start()

    def _tick_refresh(self):
        if not self._poll_paused:
            self._refresh_device()
        return True

    # ------------------------------------------------------- al conectar
    # Sondeo propio de 2 s, y solo con la opción activa: el refresco normal es
    # cada 10 s y lee batería, pantalla y roles, demasiado para «luego luego».
    # Este solo pregunta `adb devices`, que no llega a tocar el móvil.
    SEGUNDOS_SONDEO_AUTO = 2

    def _programar_auto(self):
        if self._auto_modo and not self._auto_source:
            self._auto_source = GLib.timeout_add_seconds(self.SEGUNDOS_SONDEO_AUTO, self._tick_auto)
        elif not self._auto_modo and self._auto_source:
            GLib.source_remove(self._auto_source)
            self._auto_source = 0

    def _tick_auto(self):
        if not self._auto_modo:
            self._auto_source = 0
            return False
        if self._poll_paused or self._auto_sondeando:
            return True
        self._auto_sondeando = True

        def _on_done(result):
            GLib.idle_add(self._on_auto_sondeo, result, worker)

        def _on_error(_err):
            GLib.idle_add(self._on_auto_sondeo, {'success': False}, worker)

        worker = CommandWorker({'id': 'auto', 'titulo': 'auto', 'desc': '', 'accion': 'devices_ready'},
                               None, None, on_done=_on_done, on_error=_on_error)
        self._workers.add(worker)
        worker.start()
        return True

    def _on_auto_sondeo(self, result, worker):
        self._workers.discard(worker)
        self._auto_sondeando = False
        if not result.get('success'):
            return False
        self._auto_conectado = bool((result.get('info') or {}).get('listos'))
        if self._auto_modo and self._auto.actualizar(self._auto_conectado):
            self._abrir_al_conectar()
        return False

    def _abrir_al_conectar(self):
        self._refresh_device()
        spec, valores = spec_auto_conectar(self._auto_modo, self._catalogo,
                                           getattr(self, '_device_info', None))
        if spec is None:
            self._log(f'Móvil conectado, pero «{AUTO_CONECTAR[self._auto_modo]}» no se puede abrir '
                      'con el scrcpy de este PC.', kind='error')
            return
        self._log(f'📱 Móvil conectado: {AUTO_CONECTAR[self._auto_modo]}…')
        self._launch(spec, valores)

    # ----------------------------------------------------------------- theme
    def _apply_theme(self, theme):
        display = Gdk.Display.get_default()
        if display is None:
            return
        css, modo, fuente = get_theme_css(theme)
        provider = Gtk.CssProvider()
        try:
            provider.load_from_string(css)
        except Exception as e:
            self._log(f'CSS del tema no válido: {e}', kind='error')
            return
        if self._provider:
            try:
                Gtk.StyleContext.remove_provider_for_display(display, self._provider)
            except Exception:
                pass
        Gtk.StyleContext.add_provider_for_display(display, provider, _PRIORITY)
        self._provider = provider
        self._set_dark_preference(modo == 'dark')
        if fuente in ('matugen:nodisponible', 'matugen:sincolores') and not self._theme_warned:
            self._theme_warned = True
            self._log('Tema matugen: no hay CSS generado con colores reconocibles; se usa la paleta oscura '
                      'hasta que aparezca ~/.config/gekko-adb/matugen.css o ~/.cache/matugen/colors-gtk.css.')

    def _set_dark_preference(self, dark):
        try:
            settings = Gtk.Settings.get_default()
            if settings is not None:
                settings.props.gtk_application_prefer_dark_theme = dark
        except Exception:
            pass

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
        self._theme_warned = False
        self._apply_theme(self._theme)
        return False


def main():
    app = GekkoAdbGtk4App()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
