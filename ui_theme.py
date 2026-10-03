"""Compatibility import for the default light theme.

The active appearance settings and palette live in theme_manager.py.
"""

from theme_manager import ThemeManager, ThemePreferences

APP_STYLE = ThemeManager.stylesheet(ThemePreferences())
