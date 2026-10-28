"""Portable visual palettes; no GUI dependency in theme metadata.

`agent_change`, `human_change` and `proposal` color the pattern cells that a collaborator
changed or proposed (see PatternModel.flash and PatternModel.set_overlay)."""

from string import Template

THEMES = {
    "midnight": dict(name="Midnight", bg="#101722", panel="#151f2d", text="#e4ecf5", muted="#abb7cb",
        border="#2b3a4f", button="#213147", hover="#2c435e", selected="#30465c", accent="#8fd8e8",
        primary="#28596b", primary_text="#ffffff", header="#1d2b3d", beat="#1c2a3c", playing="#2f4760",
        loop="#1c3d46", error="#f4b5ac", disabled="#718096", meter="#7bd7a0", warning="#f1c36e",
        agent_change="#1e4c43", proposal="#4a3d73", human_change="#574127",
        channels=("#8fd8e8", "#f4bc7b", "#b8d79b", "#c3a6ef")),
    "amber": dict(name="Amber", bg="#1a1711", panel="#242016", text="#f6e9cb", muted="#c6b79b",
        border="#4b4029", button="#352c1c", hover="#4b3d24", selected="#524129", accent="#f0bc66",
        primary="#765026", primary_text="#fff4df", header="#332b1d", beat="#2b251a", playing="#544023",
        loop="#463a22", error="#f0a997", disabled="#8c7e64", meter="#c8d484", warning="#f0bc66",
        agent_change="#284b33", proposal="#4b3a66", human_change="#5d3a23",
        channels=("#f0bc66", "#b6d1a1", "#dca0ac", "#a6c7d1")),
    "violet": dict(name="Violet", bg="#171322", panel="#211b30", text="#f0e9fa", muted="#b7abcd",
        border="#423454", button="#30253f", hover="#483359", selected="#503b66", accent="#d0a6fa",
        primary="#634381", primary_text="#ffffff", header="#30243f", beat="#2b2039", playing="#523968",
        loop="#3e2d51", error="#f5b1c7", disabled="#8c7c9d", meter="#8cdbbf", warning="#f4c481",
        agent_change="#234f46", proposal="#4e406d", human_change="#60422a",
        channels=("#d0a6fa", "#8cdbbf", "#f3bd8a", "#9cbff2")),
    "light": dict(name="Light", bg="#eef2f6", panel="#ffffff", text="#1b2b3e", muted="#4e6075",
        border="#becbd8", button="#e1e9f0", hover="#d0e0ed", selected="#c2dced", accent="#16647b",
        primary="#1b657c", primary_text="#ffffff", header="#dce6ef", beat="#edf3f8", playing="#c0dced",
        loop="#d2e8e9", error="#a02d32", disabled="#798793", meter="#24744c", warning="#815310",
        agent_change="#bde8cf", proposal="#ddcff3", human_change="#f6dcae",
        channels=("#12637c", "#8f4b00", "#316823", "#76429b")),
}



MONO = '"Cascadia Mono","Consolas","DejaVu Sans Mono",monospace'


def mix(color: str, other: str, amount: float) -> str:
    """`color` blended `amount` (0..1) toward `other`, both "#rrggbb"."""
    a, b = (tuple(int(value[i:i + 2], 16) for i in (1, 3, 5)) for value in (color, other))
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def icon_colors(theme: str) -> dict[str, str]:
    """Colours of the small glyphs the stylesheet draws as images (check mark, chevrons)."""
    p = THEMES[theme]
    return {"check": "#ffffff" if theme == "light" else p["bg"], "chevron": p["muted"], "chevron_off": p["disabled"]}


def stylesheet(theme: str, icons: dict[str, str] | None = None) -> str:
    """The Qt stylesheet of a theme. `icons` maps glyph names (check, up, down, up_off, down_off) to image
    paths (see desktop_widgets.ui_icons); without it the indicators fall back to plain fills."""
    p = dict(THEMES[theme])
    p.update(grid=mix(p["border"], p["panel"], .45), mono=MONO)
    q = {key: "url(\"" + str(path).replace("\\", "/") + "\")" for key, path in (icons or {}).items()}
    check = f"image:{q['check']};" if "check" in q else ""
    arrows = ""
    if "down" in q:
        arrows = (f"QComboBox::down-arrow {{image:{q['down']};width:10px;height:10px}} "
                  f"QComboBox::down-arrow:disabled {{image:{q['down_off']}}} "
                  f"QSpinBox::up-arrow,QDoubleSpinBox::up-arrow {{image:{q['up']};width:9px;height:9px}} "
                  f"QSpinBox::down-arrow,QDoubleSpinBox::down-arrow {{image:{q['down']};width:9px;height:9px}} "
                  f"QSpinBox::up-arrow:disabled,QDoubleSpinBox::up-arrow:disabled {{image:{q['up_off']}}} "
                  f"QSpinBox::down-arrow:disabled,QDoubleSpinBox::down-arrow:disabled {{image:{q['down_off']}}}")
    p.update(check=check, arrows=arrows)
    return Template(STYLE_TEMPLATE).substitute(p)


STYLE_TEMPLATE = """
/* --- base --- */
QMainWindow,QDialog,QWidget {background:$bg;color:$text;font-size:13px}
QLabel {background:transparent}
QLabel#muted {color:$muted}
QLabel#section {font-family:$mono;font-size:11px;font-weight:700;color:$accent;padding-top:6px}
QLabel#itemTitle {font-size:15px;font-weight:600}
QLabel[error="true"] {color:$error}
QToolTip {background:$panel;color:$text;border:1px solid $border;padding:4px 6px}
QMenuBar {background:$panel;border-bottom:1px solid $border;padding:1px 4px}
QMenuBar::item {background:transparent;padding:4px 10px;border-radius:4px}
QMenuBar::item:selected {background:$selected}
QMenu {background:$panel;border:1px solid $border;padding:4px}
QMenu::item {padding:5px 24px 5px 18px;border-radius:4px}
QMenu::item:selected {background:$selected}
QMenu::item:disabled {color:$disabled}
QMenu::separator {height:1px;background:$border;margin:4px 6px}
QStatusBar {background:$panel;border-top:1px solid $border}
QStatusBar::item {border:0}
QLabel#webStatus {color:$accent;padding:0 8px}

/* --- header band --- */
QFrame#header {background:$panel;border:0;border-bottom:1px solid $border}
QFrame#header QLineEdit,QFrame#header QSpinBox,QFrame#header QComboBox {background:$bg}
QFrame#separator {background:$border;border:0;min-width:1px;max-width:1px}
QLineEdit#songTitle {font-size:18px;font-weight:600;padding:3px 10px}
QLabel#formatBadge {background:$header;border:1px solid $border;border-radius:11px;padding:2px 10px;font-family:$mono;font-size:11px;font-weight:600}

/* --- buttons --- */
QPushButton {background:$button;border:1px solid $border;border-radius:6px;padding:4px 12px;min-height:20px}
QPushButton:hover {background:$hover}
QPushButton:pressed {background:$selected}
QPushButton:checked {background:$selected;border-color:$accent}
QPushButton:focus {border-color:$accent}
QPushButton:disabled {color:$disabled;background:transparent;border-color:$border}
QPushButton#primary {background:$primary;color:$primary_text;border-color:$accent;font-weight:700}
QPushButton#primary:hover {background:$primary;border-color:$text}
QPushButton#primary:disabled {color:$disabled;background:transparent;border-color:$border;font-weight:600}
QPushButton[compact="true"] {padding:4px 8px}
QPushButton[tone="apply"] {border-color:$accent;color:$accent}
QPushButton[tone="apply"]:disabled {color:$disabled;border-color:$border}
QPushButton[trackMuted="true"] {color:$disabled;background:transparent;border-color:$border}
QPushButton[solo="true"]:checked {background:$warning;color:$bg;border-color:$warning;font-weight:700}
QPushButton#helpButton {border-radius:12px;padding:0;min-width:24px;max-width:24px;min-height:22px;max-height:24px;font-weight:700}

/* --- fields --- */
QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QPlainTextEdit,QTextEdit {background:$panel;border:1px solid $border;border-radius:6px;padding:4px 8px;min-height:20px;selection-background-color:$selected;selection-color:$text}
QLineEdit:hover,QSpinBox:hover,QDoubleSpinBox:hover,QComboBox:hover {border-color:$disabled}
QLineEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,QComboBox:focus,QPlainTextEdit:focus,QListWidget:focus,QTableView:focus,QTreeWidget:focus {border-color:$accent}
QLineEdit:disabled,QSpinBox:disabled,QDoubleSpinBox:disabled,QComboBox:disabled {color:$disabled;background:transparent}
QPlainTextEdit {padding:6px 8px}
QSpinBox,QDoubleSpinBox {padding:4px 22px 4px 8px}
QSpinBox::up-button,QDoubleSpinBox::up-button {subcontrol-origin:border;subcontrol-position:top right;width:20px;border:0;border-left:1px solid $border;border-top-right-radius:5px;background:transparent}
QSpinBox::down-button,QDoubleSpinBox::down-button {subcontrol-origin:border;subcontrol-position:bottom right;width:20px;border:0;border-left:1px solid $border;border-bottom-right-radius:5px;background:transparent}
QSpinBox::up-button:hover,QDoubleSpinBox::up-button:hover,QSpinBox::down-button:hover,QDoubleSpinBox::down-button:hover {background:$hover}
QComboBox {padding:4px 26px 4px 8px}
QComboBox::drop-down {subcontrol-origin:padding;subcontrol-position:center right;width:24px;border:0}
QComboBox QAbstractItemView {background:$panel;border:1px solid $border;selection-background-color:$selected;selection-color:$text;outline:0;padding:2px}
$arrows
QCheckBox {spacing:8px;padding:2px 0}
QCheckBox:focus {color:$accent}
QCheckBox::indicator {width:16px;height:16px;border:1px solid $disabled;border-radius:4px;background:$panel}
QCheckBox::indicator:hover {border-color:$accent}
QCheckBox::indicator:checked {background:$accent;border-color:$accent;$check}
QCheckBox::indicator:disabled {border-color:$border;background:transparent}
QSlider::groove:horizontal {height:4px;background:$border;border-radius:2px}
QSlider::sub-page:horizontal {background:$accent;border-radius:2px}
QSlider::handle:horizontal {background:$text;border:2px solid $accent;width:10px;height:10px;margin:-6px 0;border-radius:7px}
QSlider::handle:horizontal:hover {background:$accent}

/* --- tabs, splitters, scrolling --- */
QTabWidget::pane {border:0;border-top:1px solid $border;top:-1px}
QTabBar {background:transparent}
QTabBar::tab {background:transparent;color:$muted;border:0;border-bottom:2px solid transparent;padding:7px 14px;margin-right:2px}
QTabBar::tab:hover {color:$text;background:$button}
QTabBar::tab:selected {color:$text;border-bottom:2px solid $accent}
QSplitter::handle:horizontal {background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 $bg,stop:.4 $bg,stop:.41 $border,stop:.59 $border,stop:.6 $bg,stop:1 $bg)}
QSplitter::handle:vertical {background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 $bg,stop:.4 $bg,stop:.41 $border,stop:.59 $border,stop:.6 $bg,stop:1 $bg)}
QSplitter::handle:horizontal:hover {background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 $bg,stop:.3 $bg,stop:.31 $accent,stop:.69 $accent,stop:.7 $bg,stop:1 $bg)}
QSplitter::handle:vertical:hover {background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 $bg,stop:.3 $bg,stop:.31 $accent,stop:.69 $accent,stop:.7 $bg,stop:1 $bg)}
QScrollArea {background:transparent;border:0}
QAbstractScrollArea::corner {background:$bg}
QScrollBar:vertical {background:transparent;width:12px;margin:0}
QScrollBar:horizontal {background:transparent;height:12px;margin:0}
QScrollBar::handle:vertical {background:$disabled;min-height:28px;border-radius:4px;margin:2px}
QScrollBar::handle:horizontal {background:$disabled;min-width:28px;border-radius:4px;margin:2px}
QScrollBar::handle:hover {background:$muted}
QScrollBar::add-line,QScrollBar::sub-line {width:0;height:0;border:0;background:none}
QScrollBar::add-page,QScrollBar::sub-page {background:transparent}

/* --- lists, trees and the grid --- */
QTreeWidget,QListWidget,QTableView,QTableWidget {background:$panel;border:1px solid $border;border-radius:6px;selection-background-color:$selected;selection-color:$text;outline:0}
QTreeWidget::item,QListWidget::item {padding:5px 6px;border-radius:4px}
QTreeWidget::item:hover,QListWidget::item:hover {background:$beat}
QTreeWidget::item:selected,QListWidget::item:selected {background:$selected;color:$text}
QWidget#sampleLibraryBrowser QPushButton {padding:4px 8px}
QWidget#sampleLibraryBrowser QLabel#section {padding-top:0}
QListWidget#librarySamples::item {padding:4px 6px}
QTableView {gridline-color:$grid}
QTableView#patterns[editMode="true"] {border:2px solid $accent}
QHeaderView {background:$header}
QHeaderView::section {background:$header;color:$muted;border:0;border-right:1px solid $border;border-bottom:1px solid $border;padding:5px 8px;font-size:12px;font-weight:600}
QHeaderView::section:vertical {padding:0 6px;border-right:1px solid $border;border-bottom:1px solid $grid;font-weight:500}
QTableCornerButton::section {background:$header;border:0}
QWidget#waveEditor {border:1px solid $border;border-radius:6px}
QFrame#shortcutPopup {background:$panel;border:1px solid $border;border-radius:8px}
QLabel#shortcutKeys {font-family:$mono;font-size:12px;font-weight:600;color:$accent}
QLabel#compareState {font-weight:bold}
QLabel#compareState[side="A"] {color:$accent}
QLabel#compareState[side="B"] {color:$warning}
QDialog {background:$bg}
"""
