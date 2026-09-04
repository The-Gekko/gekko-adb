# Graph Report - Gekko ADB  (2026-08-23)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 280 nodes · 509 edges · 13 communities (7 shown, 6 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b0961b19`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- gekko_adb_core.py
- GekkoAdbGtk4App
- GekkoAdbGtk3App
- TestEjecucion
- gekko-adb-gtk4.py
- get_battery
- .run
- install.sh
- TestBateria
- TestTheme
- TestGtk3
- TestGtk4
- gekko-adb

## God Nodes (most connected - your core abstractions)
1. `run_adb()` - 58 edges
2. `GekkoAdbGtk4App` - 44 edges
3. `GekkoAdbGtk3App` - 41 edges
4. `install.sh script` - 11 edges
5. `TestEjecucion` - 10 edges
6. `start_command()` - 10 edges
7. `get_theme_css()` - 10 edges
8. `TestBateria` - 9 edges
9. `css()` - 9 edges
10. `user_dir()` - 8 edges

## Surprising Connections (you probably didn't know these)
- `start_command()` --calls--> `CommandWorker`  [EXTRACTED]
  gekko_adb_core.py → gekko_adb_core.py  _Bridges community 6 → community 4_
- `get_device_info()` --calls--> `get_devices()`  [EXTRACTED]
  gekko_adb_core.py → gekko_adb_core.py  _Bridges community 0 → community 5_
- `run_adb()` --calls--> `adb_base_args()`  [EXTRACTED]
  gekko_adb_core.py → gekko_adb_core.py  _Bridges community 0 → community 6_

## Import Cycles
- None detected.

## Communities (13 total, 6 thin omitted)

### Community 0 - "gekko_adb_core.py"
Cohesion: 0.06
Nodes (68): act_anim_scale(), act_bugreport(), act_connect(), act_custom(), act_debloat_preset(), act_density(), act_density_reset(), act_devices() (+60 more)

### Community 2 - "GekkoAdbGtk3App"
Cohesion: 0.09
Nodes (3): css(), GekkoAdbGtk3App, main()

### Community 3 - "TestEjecucion"
Cohesion: 0.08
Nodes (5): Todo campo pedido por la UI debe existir en build_valores., TestCatalogoIntegridad, TestCommandWorker, TestConfig, TestEjecucion

### Community 4 - "gekko-adb-gtk4.py"
Cohesion: 0.18
Nodes (17): cargar_config(), guardar_config(), load_catalogo(), load_presets(), preset_buttons(), Convierte cada preset en una especificación de catálogo ejecutable., start_command(), find_matugen_css() (+9 more)

### Community 5 - "get_battery"
Cohesion: 0.12
Nodes (17): act_device_info(), _battery_clean(), _battery_sysfs(), connectividad(), get_battery(), get_device_info(), _normalize_battery(), _parse_battery_properties() (+9 more)

### Community 6 - ".run"
Cohesion: 0.14
Nodes (12): act_help(), act_kill_server(), act_start_server(), act_version(), adb_base_args(), build_valores(), CommandWorker, ejecutar() (+4 more)

### Community 7 - "install.sh"
Cohesion: 0.36
Nodes (11): check_package(), fail(), fetch_sources(), info(), install_core(), install_deps(), ok(), install.sh script (+3 more)

## Knowledge Gaps
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `GekkoAdbGtk4App` connect `GekkoAdbGtk4App` to `gekko-adb-gtk4.py`?**
  _High betweenness centrality (0.177) - this node is a cross-community bridge._
- **Why does `GekkoAdbGtk3App` connect `GekkoAdbGtk3App` to `gekko-adb-gtk4.py`?**
  _High betweenness centrality (0.143) - this node is a cross-community bridge._
- **Why does `start_command()` connect `gekko-adb-gtk4.py` to `gekko_adb_core.py`, `GekkoAdbGtk4App`, `GekkoAdbGtk3App`, `.run`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Should `gekko_adb_core.py` be split into smaller, more focused modules?**
  _Cohesion score 0.058823529411764705 - nodes in this community are weakly interconnected._
- **Should `GekkoAdbGtk4App` be split into smaller, more focused modules?**
  _Cohesion score 0.08305647840531562 - nodes in this community are weakly interconnected._
- **Should `GekkoAdbGtk3App` be split into smaller, more focused modules?**
  _Cohesion score 0.09390243902439024 - nodes in this community are weakly interconnected._
- **Should `TestEjecucion` be split into smaller, more focused modules?**
  _Cohesion score 0.08262108262108261 - nodes in this community are weakly interconnected._