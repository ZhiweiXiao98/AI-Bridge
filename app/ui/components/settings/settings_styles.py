from app.ui.theme import theme_manager


def nav_bar_style():
    p = theme_manager.get_palette()
    return f"""
        QFrame#settingsNavBar {{
            background-color: {p.BG_SECONDARY};
            border-right: 1px solid {p.BORDER};
            border-radius: 0px;
        }}
        QListWidget#settingsNavList {{
            background-color: transparent;
            border: none;
            outline: none;
            padding: 8px 4px;
        }}
        QListWidget#settingsNavList::item {{
            color: {p.TEXT_SECONDARY};
            padding: 10px 16px;
            margin: 2px 6px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
        }}
        QListWidget#settingsNavList::item:selected {{
            background-color: {p.ACCENT_PRIMARY};
            color: #FFFFFF;
            font-weight: 600;
        }}
        QListWidget#settingsNavList::item:hover:!selected {{
            background-color: {p.BG_TERTIARY};
            color: {p.TEXT_PRIMARY};
        }}
    """


def section_style():
    p = theme_manager.get_palette()
    return f"""
        QScrollArea#settingsSectionScroll {{
            background-color: {p.BG_PRIMARY};
            border: none;
        }}
        QWidget#settingsSectionContent {{
            background-color: {p.BG_PRIMARY};
        }}
    """


def card_style():
    p = theme_manager.get_palette()
    return f"""
        QFrame#settingsCard {{
            background-color: {p.BG_SECONDARY};
            border: 1px solid {p.BORDER};
            border-radius: 12px;
        }}
        QLabel#settingsCardTitle {{
            color: {p.TEXT_PRIMARY};
            font-size: 15px;
            font-weight: 700;
            padding-bottom: 4px;
            background: transparent;
        }}
    """


def field_style():
    p = theme_manager.get_palette()
    return f"""
        QFrame#settingsField {{
            background: transparent;
        }}
        QLabel#settingsFieldLabel {{
            color: {p.TEXT_SECONDARY};
            font-size: 12px;
            font-weight: 600;
            background: transparent;
        }}
        QLabel#settingsFieldDesc {{
            color: {p.TEXT_SECONDARY};
            font-size: 11px;
            background: transparent;
        }}
    """


def toggle_row_style():
    p = theme_manager.get_palette()
    return f"""
        QFrame#settingsToggleRow {{
            background-color: {p.BG_TERTIARY};
            border: 1px solid transparent;
            border-radius: 10px;
        }}
        QFrame#settingsToggleRow:hover {{
            border: 1px solid {p.BORDER};
        }}
        QLabel#settingsToggleTitle {{
            color: {p.TEXT_PRIMARY};
            font-weight: 600;
            font-size: 13px;
            background: transparent;
        }}
        QLabel#settingsToggleDesc {{
            color: {p.TEXT_SECONDARY};
            font-size: 11px;
            background: transparent;
        }}
    """


def field_row_style():
    p = theme_manager.get_palette()
    return f"""
        QFrame#settingsFieldRow {{
            background: transparent;
        }}
    """


def bottom_bar_style():
    p = theme_manager.get_palette()
    return f"""
        QFrame#settingsBottomBar {{
            background-color: {p.BG_SECONDARY};
            border-top: 1px solid {p.BORDER};
        }}
    """


def radio_button_style():
    p = theme_manager.get_palette()
    return f"""
        QRadioButton {{
            color: {p.TEXT_PRIMARY};
            spacing: 8px;
            background: transparent;
        }}
        QRadioButton::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 8px;
            border: 2px solid {p.BORDER};
            background-color: {p.BG_SECONDARY};
        }}
        QRadioButton::indicator:checked {{
            border: 2px solid {p.ACCENT_PRIMARY};
            background-color: {p.ACCENT_PRIMARY};
        }}
    """


def all_styles():
    return (
        nav_bar_style()
        + section_style()
        + card_style()
        + field_style()
        + toggle_row_style()
        + field_row_style()
        + bottom_bar_style()
        + radio_button_style()
    )
