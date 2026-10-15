"""Portable visual palettes; no GUI dependency in theme metadata."""

THEMES = {
    "midnight": dict(name="Midnight", bg="#101722", panel="#151f2d", text="#e4ecf5", muted="#9cadc1",
        border="#2b3a4f", button="#213147", hover="#2c435e", selected="#30465c", accent="#8fd8e8",
        primary="#28596b", primary_text="#ffffff", header="#1d2b3d", beat="#1c2a3c", playing="#304963",
        loop="#1c3d46", error="#f4b5ac", disabled="#718096", meter="#7bd7a0", warning="#f1c36e",
        channels=("#8fd8e8", "#f4bc7b", "#b8d79b", "#c3a6ef")),
    "amber": dict(name="Amber", bg="#1a1711", panel="#242016", text="#f6e9cb", muted="#baaa88",
        border="#4b4029", button="#352c1c", hover="#4b3d24", selected="#56452b", accent="#f0bc66",
        primary="#765026", primary_text="#fff4df", header="#332b1d", beat="#2b251a", playing="#5b4626",
        loop="#463a22", error="#f0a997", disabled="#8c7e64", meter="#c8d484", warning="#f0bc66",
        channels=("#f0bc66", "#b6d1a1", "#dca0ac", "#a6c7d1")),
    "violet": dict(name="Violet", bg="#171322", panel="#211b30", text="#f0e9fa", muted="#b3a5c9",
        border="#423454", button="#30253f", hover="#483359", selected="#503b66", accent="#d0a6fa",
        primary="#634381", primary_text="#ffffff", header="#30243f", beat="#2b2039", playing="#523968",
        loop="#3e2d51", error="#f5b1c7", disabled="#8c7c9d", meter="#8cdbbf", warning="#f4c481",
        channels=("#d0a6fa", "#8cdbbf", "#f3bd8a", "#9cbff2")),
    "light": dict(name="Light", bg="#eef2f6", panel="#ffffff", text="#1b2b3e", muted="#52667d",
        border="#becbd8", button="#e1e9f0", hover="#d0e0ed", selected="#c2dced", accent="#17677f",
        primary="#1b657c", primary_text="#ffffff", header="#dce6ef", beat="#edf3f8", playing="#c0dced",
        loop="#d2e8e9", error="#a02d32", disabled="#7d8b98", meter="#24744c", warning="#a46b12",
        channels=("#166a84", "#985100", "#376f26", "#76429b")),
}


def stylesheet(theme: str) -> str:
    p = THEMES[theme]
    return """
QMainWindow,QWidget {{background:{bg};color:{text};font-size:13px}}
QMenuBar,QMenu,QStatusBar {{background:{panel}}} QMenu::item:selected {{background:{selected}}}
QTreeWidget,QListWidget,QTableView,QLineEdit,QSpinBox,QComboBox {{background:{panel};border:1px solid {border};border-radius:5px;padding:4px;selection-background-color:{selected};selection-color:{text}}}
QTreeWidget::item,QListWidget::item {{padding:7px}} QTreeWidget::item:selected,QListWidget::item:selected {{background:{selected}}}
QPushButton {{background:{button};border:1px solid {border};border-radius:6px;padding:7px 12px}}
QPushButton:hover {{background:{hover}}} QPushButton:checked {{background:{selected};border-color:{accent}}}
QPushButton:disabled {{color:{disabled};background:{panel}}}
QPushButton#primary {{background:{primary};color:{primary_text};border-color:{accent};font-weight:bold}}
QPushButton[trackMuted="true"] {{color:{disabled};background:{panel};border-color:{disabled}}}
QHeaderView::section {{background:{header};color:{text};border:0;border-right:1px solid {border};padding:8px}}
QTableView {{gridline-color:{border};selection-background-color:{selected};selection-color:{text}}}
QLabel#title {{font-size:29px;font-weight:600}} QLabel#muted {{color:{muted}}}
QLabel#section {{font-size:14px;font-weight:bold;color:{accent};padding-top:8px}}
QToolTip {{background:{panel};color:{text};border:1px solid {border}}}
QSplitter::handle {{background:{border}}} QSlider::groove:horizontal {{height:5px;background:{border};border-radius:2px}}
QSlider::handle:horizontal {{background:{accent};border:0;width:12px;margin:-5px 0;border-radius:6px}}
""".format(**p)
