"""PDFRush visual design: palette, stylesheet and line icons (drawn from inline SVG)."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

BG = "#0B0D12"
SURFACE = "#12151D"
SURFACE2 = "#181C27"
SURFACE3 = "#1F2432"
BORDER = "#262C3D"
TEXT = "#ECEEF5"
MUTED = "#8C93A9"
FAINT = "#5D6479"
ACCENT = "#FF5A5F"
ACCENT2 = "#FF9F43"
SUCCESS = "#3DDC97"
WARN = "#FFC857"
DANGER = "#FF6B7A"
GRAD = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {ACCENT}, stop:1 {ACCENT2})"
GRAD_HOVER = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FF7478, stop:1 #FFB46B)"


FONT = "'Segoe UI Variable Text', 'Segoe UI', 'Inter', sans-serif"

STYLE = f"""
* {{ font-family: {FONT}; font-size: 13px; color: {TEXT}; outline: none; }}
QMainWindow, QWidget#root, QStackedWidget, QWidget#page {{ background: {BG}; }}
QWidget#sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QLabel {{ background: transparent; }}
QLabel#h1 {{ font-size: 26px; font-weight: 700; letter-spacing: -0.3px; }}
QLabel#h2 {{ font-size: 16px; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#faint {{ color: {FAINT}; font-size: 12px; }}
QLabel#pill {{ background: {SURFACE3}; border: 1px solid {BORDER}; border-radius: 11px; padding: 3px 10px;
               font-weight: 600; font-size: 12px; }}
QLabel#brand {{ font-size: 19px; font-weight: 800; letter-spacing: -0.2px; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px; }}
QFrame#card2 {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#tile {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 18px; }}
QFrame#tile:hover {{ background: {SURFACE2}; border-color: #3A4260; }}
QFrame#drop {{ background: {SURFACE}; border: 2px dashed #313852; border-radius: 18px; }}
QFrame#drop[hover="true"] {{ border-color: {ACCENT}; background: #1A1418; }}
QFrame#activity {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
QFrame#toast {{ background: {SURFACE3}; border: 1px solid #3A4260; border-radius: 12px; }}
QFrame#sep {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}

QPushButton {{ background: {SURFACE3}; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px 14px;
               font-weight: 600; }}
QPushButton:hover {{ background: #262C3D; border-color: #343B53; }}
QPushButton:pressed {{ background: #1B2030; }}
QPushButton:disabled {{ color: {FAINT}; background: {SURFACE2}; }}
QPushButton#primary {{ background: {GRAD}; color: #0B0D12; border: none; font-weight: 700; padding: 10px 22px; }}
QPushButton#primary:hover {{ background: {GRAD_HOVER}; }}
QPushButton#primary:disabled {{ background: #2A3046; color: {FAINT}; }}
QPushButton#ghost {{ background: transparent; border: none; color: {MUTED}; padding: 6px 8px; }}
QPushButton#ghost:hover {{ color: {TEXT}; background: {SURFACE3}; }}
QPushButton#nav {{ text-align: left; padding: 10px 14px; border: none; border-radius: 10px; background: transparent;
                   color: {MUTED}; font-size: 14px; font-weight: 600; }}
QPushButton#nav:hover {{ background: {SURFACE2}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {SURFACE3}; color: {TEXT}; }}
QPushButton#seg {{ background: transparent; border: none; border-radius: 8px; padding: 7px 14px; color: {MUTED}; }}
QPushButton#seg:hover {{ color: {TEXT}; }}
QPushButton#seg:checked {{ background: {SURFACE3}; color: {TEXT}; border: 1px solid #3A4260; }}
QFrame#segbar {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 11px; }}
QPushButton#toggle {{ min-width: 30px; max-width: 30px; min-height: 26px; padding: 0; border-radius: 8px; font-weight: 800; }}
QPushButton#toggle:checked {{ background: {ACCENT}; color: #0B0D12; border: none; }}
QPushButton#mute:checked {{ background: {DANGER}; color: #0B0D12; border: none; }}
QPushButton#round {{ border-radius: 22px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px;
                     padding: 0; background: {GRAD}; border: none; }}
QPushButton#round:hover {{ background: {GRAD_HOVER}; }}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QListWidget {{
    background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 7px 10px;
    selection-background-color: #5A2A30; }}
QComboBox:hover, QLineEdit:hover, QPlainTextEdit:hover {{ border-color: #3A4260; }}
QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {SURFACE2}; border: 1px solid {BORDER}; selection-background-color: {SURFACE3};
                               padding: 4px; }}
QPlainTextEdit {{ font-size: 15px; padding: 12px; }}
QListWidget {{ padding: 6px; }}
QListWidget::item {{ padding: 9px 8px; border-radius: 8px; }}
QListWidget::item:hover {{ background: {SURFACE3}; }}
QListWidget::item:selected {{ background: #3A1F26; color: {TEXT}; }}
QCheckBox {{ spacing: 8px; color: {TEXT}; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid #3A4260; background: {SURFACE2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QProgressBar {{ background: {SURFACE3}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px;
                text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {GRAD}; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 4px; background: {SURFACE3}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {GRAD}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #FFFFFF; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2C3247; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3A4260; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
QToolTip {{ background: {SURFACE3}; color: {TEXT}; border: 1px solid #3A4260; border-radius: 6px; padding: 6px; }}
QMessageBox, QDialog {{ background: {SURFACE}; }}
QMenu {{ background: {SURFACE2}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE3}; }}
QFrame#chipbar QPushButton {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 15px; padding: 6px 14px;
                              color: {MUTED}; font-weight: 600; }}
QFrame#chipbar QPushButton:hover {{ color: {TEXT}; border-color: #3A4260; }}
QFrame#chipbar QPushButton:checked {{ background: {TEXT}; color: {BG}; border-color: {TEXT}; }}
QLabel#newpill {{ background: {ACCENT}; color: #0B0D12; border-radius: 8px; padding: 1px 7px; font-size: 10px;
                  font-weight: 800; }}
QLabel#tiletitle {{ font-size: 15px; font-weight: 700; }}
QLabel#tiledesc {{ color: {MUTED}; font-size: 12px; }}
QLineEdit#search {{ font-size: 14px; padding: 10px 14px; border-radius: 14px; }}
QListWidget#thumbs {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; padding: 10px; }}
QListWidget#thumbs::item {{ padding: 6px; border-radius: 10px; color: {MUTED}; }}
QListWidget#thumbs::item:selected {{ background: #3A1F26; border: 1px solid {ACCENT}; color: {TEXT}; }}
QFrame#canvasbox {{ background: #07080C; border: 1px solid {BORDER}; border-radius: 14px; }}
QPushButton#toolbtn {{ background: transparent; border: 1px solid transparent; border-radius: 9px; padding: 7px 10px;
                       color: {MUTED}; text-align: left; }}
QPushButton#toolbtn:hover {{ background: {SURFACE2}; color: {TEXT}; }}
QPushButton#toolbtn:checked {{ background: {SURFACE3}; color: {TEXT}; border-color: {ACCENT}; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 14px; border: none; font-weight: 600; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTableWidget {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 10px; gridline-color: {BORDER}; }}
QHeaderView::section {{ background: {SURFACE3}; color: {MUTED}; border: none; padding: 6px; font-weight: 600; }}
"""

# ------------------------------------------------------------------ icons (24x24 line icons)
_P = {
    "merge": '<path d="M8 3v5a4 4 0 004 4h0a4 4 0 014 4v5"/><path d="M16 3v5a4 4 0 01-4 4"/><path d="M5 18l3 3 3-3" opacity="0"/><path d="M13 18l3 3 3-3"/>',
    "split": '<path d="M12 21v-7a4 4 0 00-4-4H4"/><path d="M12 14a4 4 0 014-4h4"/><path d="M7 7l-3 3 3 3"/><path d="M17 7l3 3-3 3"/>',
    "rotate": '<path d="M20 11a8 8 0 10-2.3 5.7"/><path d="M20 4v7h-7"/>',
    "extract": '<rect x="4" y="3" width="11" height="14" rx="2"/><path d="M13 13h8M18 10l3 3-3 3"/>',
    "organize": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="9" rx="1.5"/><rect x="3" y="15" width="7" height="6" rx="1.5"/><rect x="14" y="15" width="7" height="6" rx="1.5"/>',
    "compress": '<path d="M4 14h6v6"/><path d="M20 10h-6V4"/><path d="M14 10l7-7"/><path d="M3 21l7-7"/>',
    "repair": '<path d="M14.7 6.3a4 4 0 00-5.4 5.2L3 17.8V21h3.2l6.3-6.3a4 4 0 005.2-5.4l-2.6 2.6-2.4-.4-.4-2.4z"/>',
    "archive": '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a1 1 0 001 1h12a1 1 0 001-1V9"/><path d="M10 13h4"/>',
    "ocr": '<path d="M3 8V5a2 2 0 012-2h3"/><path d="M16 3h3a2 2 0 012 2v3"/><path d="M21 16v3a2 2 0 01-2 2h-3"/><path d="M8 21H5a2 2 0 01-2-2v-3"/><path d="M8 16l2.5-8h1L14 16"/><path d="M9 13h4"/><path d="M16 9v7"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
    "word": '<path d="M6 2h9l5 5v15H6z"/><path d="M15 2v5h5"/><path d="M8.5 11l1.5 6 2-4.5 2 4.5 1.5-6"/>',
    "ppt": '<path d="M6 2h9l5 5v15H6z"/><path d="M15 2v5h5"/><path d="M10 18v-7h2.5a2 2 0 010 4H10"/>',
    "excel": '<path d="M6 2h9l5 5v15H6z"/><path d="M15 2v5h5"/><path d="M9.5 11l5 7M14.5 11l-5 7"/>',
    "web": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 010 18"/><path d="M12 3a14 14 0 000 18"/>',
    "markdown": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 15V9l2.5 3L11 9v6"/><path d="M17 9v6M14.5 12.5L17 15l2.5-2.5"/>',
    "watermark": '<path d="M12 3s6 6.5 6 11a6 6 0 01-12 0c0-4.5 6-11 6-11z"/><path d="M9 15a3 3 0 003 3"/>',
    "numbers": '<path d="M6 2h9l5 5v15H6z"/><path d="M10 13l2-1.5V18"/><path d="M10 18h4"/>',
    "crop": '<path d="M6 2v14a2 2 0 002 2h14"/><path d="M2 6h14a2 2 0 012 2v14"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>',
    "form": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 8h10"/><rect x="7" y="12" width="10" height="3" rx="1"/><path d="M7 18.5h4"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/>',
    "sign": '<path d="M3 17c3 0 4-9 6-9s0 8 2 8 2-4 4-4 1 3 3 3 2-1 3-1"/><path d="M3 21h18"/>',
    "lock": '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 018 0v3"/><path d="M12 14v3"/>',
    "unlock": '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 017.5-2"/><path d="M12 14v3"/>',
    "redact": '<path d="M6 2h9l5 5v15H6z"/><path d="M15 2v5h5"/><rect x="8" y="11" width="9" height="3" fill="currentColor"/><path d="M8 17h5"/>',
    "compare": '<rect x="2" y="4" width="8" height="16" rx="1.5"/><rect x="14" y="4" width="8" height="16" rx="1.5"/><path d="M12 2v20" stroke-dasharray="2 2"/>',
    "ai": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    "translate": '<path d="M4 5h9"/><path d="M8.5 3v2c0 4-2 7-5 8.5"/><path d="M6 9c1.3 2 3.3 3.6 6 4.5"/><path d="M13 21l4-9 4 9"/><path d="M14.5 18h5"/>',
    "workflow": '<rect x="3" y="3" width="6" height="6" rx="1.5"/><rect x="15" y="15" width="6" height="6" rx="1.5"/><path d="M9 6h4a3 3 0 013 3v6"/><path d="M13.5 12.5L16 15l2.5-2.5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "pdf": '<path d="M6 2h9l5 5v15H6z"/><path d="M15 2v5h5"/><path d="M9 17v-5h1.5a1.5 1.5 0 010 3H9"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "rotl": '<path d="M4 11a8 8 0 112.3 5.7"/><path d="M4 4v7h7"/>',
    "rect": '<rect x="4" y="6" width="16" height="12" rx="1"/>',
    "ellipse": '<ellipse cx="12" cy="12" rx="9" ry="6"/>',
    "line": '<path d="M5 19L19 5"/>',
    "pen": '<path d="M3 21c4-1 6-5 9-8s6-4 9-9"/>',
    "highlight": '<path d="M9 11l-5 5v4h4l5-5"/><path d="M9 11l6-6 4 4-6 6z"/><path d="M14 20h7"/>',
    "eraser": '<path d="M7 21h13"/><path d="M5 15l9-9 6 6-7 7H8z"/>',
    "cursor": '<path d="M5 3l14 8-6 2-2 6z"/>',
    "date": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-7 8-7s8 3 8 7"/>',
    "zoomin": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4M8 11h6M11 8v6"/>',
    "zoomout": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4M8 11h6"/>',
    "left": '<path d="M15 6l-6 6 6 6"/>',
    "right": '<path d="M9 6l6 6-6 6"/>',
    "save": '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v5h7V3"/><rect x="8" y="13" width="8" height="5"/>',
    "open": '<path d="M14 3h7v7"/><path d="M21 3l-9 9"/><path d="M19 14v6a1 1 0 01-1 1H4a1 1 0 01-1-1V6a1 1 0 011-1h6"/>',
    "blank": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M12 9v6M9 12h6"/>',
    "home": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "stems": '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/><path d="M3 17.5l9 5 9-5" opacity=".6"/>',
    "library": '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    "cover": '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0014 0"/><path d="M12 18v4"/><path d="M8 22h8"/>',
    "speak": '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8"/><path d="M8 12h5"/>',
    "voices": '<circle cx="9" cy="8" r="4"/><path d="M2 21c0-4 3-7 7-7s7 3 7 7"/><path d="M17 4a4 4 0 010 8"/><path d="M19 14c2 1 3 3.5 3 7"/>',
    "queue": '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/>',
    "cloud": '<path d="M7 18a5 5 0 01-.6-10A6 6 0 0118 9a4.5 4.5 0 01-.5 9z"/>',
    "cpu": '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    "play": '<path d="M7 4l13 8-13 8z" fill="currentColor"/>',
    "pause": '<rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor"/><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
    "download": '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M4 20h16"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "folder": '<path d="M3 6a2 2 0 012-2h4l2 2h8a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "upload": '<path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M4 20h16"/>',
    "spark": '<path d="M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z"/>',
    "midi": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M8 5v8M12 5v8M16 5v8"/>',
    "book": '<path d="M2 5c3-1.5 7-1.5 10 1v14c-3-2.5-7-2.5-10-1z"/><path d="M22 5c-3-1.5-7-1.5-10 1v14c3-2.5 7-2.5 10-1z"/>',
    "scan": '<path d="M3 8V5a2 2 0 012-2h3"/><path d="M16 3h3a2 2 0 012 2v3"/><path d="M21 16v3a2 2 0 01-2 2h-3"/><path d="M8 21H5a2 2 0 01-2-2v-3"/><path d="M7 9h10M7 12h10M7 15h6"/>',
    "mic": '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0014 0"/><path d="M12 18v4"/>',
    "chat": '<path d="M21 12a8 8 0 01-11.6 7.1L4 20l1-4.6A8 8 0 1121 12z"/><path d="M8.5 11h.01M12 11h.01M15.5 11h.01"/>',
    "podcast": '<circle cx="12" cy="11" r="3"/><path d="M12 14v8"/><path d="M7.8 15.6a6 6 0 118.4 0"/><path d="M5 18.4a10 10 0 1114 0"/>',
    "meeting": '<rect x="3" y="4" width="18" height="12" rx="2"/><circle cx="9" cy="10" r="2"/><circle cx="15" cy="10" r="2"/><path d="M8 20h8"/><path d="M12 16v4"/>',
    "note": '<path d="M5 3h10l4 4v14H5z"/><path d="M15 3v4h4"/><path d="M8 12h8M8 16h6"/>',
    "voice": '<path d="M3 10v4M7 7v10M11 4v16M15 8v8M19 11v2"/>',
    "link": '<path d="M10 14a5 5 0 007 0l3-3a5 5 0 00-7-7l-1 1"/><path d="M14 10a5 5 0 00-7 0l-3 3a5 5 0 007 7l1-1"/>',
    "camera": '<path d="M4 7h3l2-3h6l2 3h3a1 1 0 011 1v11a1 1 0 01-1 1H4a1 1 0 01-1-1V8a1 1 0 011-1z"/><circle cx="12" cy="13" r="4"/>',
    "clipboard": '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4V3h6v1"/><path d="M9 11h6M9 15h4"/>',
    "back": '<path d="M11 6l-6 6 6 6"/><path d="M19 6l-6 6 6 6"/>',
    "forward": '<path d="M13 6l6 6-6 6"/><path d="M5 6l6 6-6 6"/>',
    "keyboard": '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
    "volume": '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16 9a4 4 0 010 6"/><path d="M19 6a8 8 0 010 12"/>',
    "quiz": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 015 .5c0 1.7-2.5 2-2.5 3.5"/><path d="M12 17h.01"/>',
    "send": '<path d="M4 12l16-8-6 16-2-6z"/>',
    "text": '<path d="M5 6h14M12 6v13M9 19h6"/>',
    "wave": '<path d="M2 12h2M6 8v8M10 4v16M14 7v10M18 10v4M22 12h-2"/>',
}


def icon(name: str, color: str = TEXT, size: int = 20) -> QIcon:
    return QIcon(pixmap(name, color, size))


def pixmap(name: str, color: str = TEXT, size: int = 20) -> QPixmap:
    from PySide6.QtSvg import QSvgRenderer
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" color="{color}">'
           f'{_P.get(name, _P["spark"])}</svg>').replace("currentColor", color)
    ratio = 2
    pm = QPixmap(QSize(size * ratio, size * ratio))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size * ratio, size * ratio))
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def dark_title_bar(widget) -> None:
    """Windows 10/11: dark window frame to match the app."""
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        val = ctypes.c_int(1)
        for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4) == 0:
                break
        color = ctypes.c_int(0x00120D0B)   # caption color (BGR) on Windows 11
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), 4)
    except Exception:
        pass
