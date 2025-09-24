#!/usr/bin/env python3
"""
Test script for the MyrientSettingsScreen.
This demonstrates the interactive settings screen functionality.
"""

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Header, Footer
from MyrientSettings import Settings
from MyrientSettingsScreen import MyrientSettingsScreen


class SettingsTestApp(App):
    """Test application for the settings screen."""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    Container {
        height: 100%;
        overflow-y: auto;
    }
    
    /* Settings Screen Styles */
    .settings-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin: 1;
        padding: 1;
    }

    .settings-section {
        margin: 1;
        padding: 1;
        border: solid $surface;
        /*border-radius: 5px;*/
    }

    .settings-section Label {
        margin-top: 1;
        margin-bottom: 0;
        text-style: bold;
    }

    .settings-section Input {
        margin-bottom: 1;
    }

    .settings-section TextArea {
        height: 6;
        margin-bottom: 1;
    }

    .action-buttons {
        margin: 2;
        padding: 1;
        text-align: center;
    }

    .action-buttons Button {
        margin: 0 1;
    }

    .status-message {
        text-align: center;
        margin: 1;
        padding: 1;
        background: $surface;
        /*border-radius: 3px;*/
    }

    .status-message.error {
        background: $error;
        color: $error-muted;
    }

    .help-text {
        color: $text-muted;
        text-style: italic;
        margin: 1 0;
    }

    #settings-scroll {
        height: 100%;
        overflow-y: auto;
    }

    Collapsible {
        margin: 1 0;
        border: solid $surface;
        /*border-radius: 5px;*/
    }

    Switch {
        margin-left: 1;
    }
    """
    
    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("q", "quit", "Quit"),
    ]
    
    def __init__(self):
        super().__init__()
        # Load existing settings or create defaults
        try:
            self.settings = Settings.load_from_file()
        except Exception:
            self.settings = Settings()
    
    def compose(self) -> ComposeResult:
        """Compose the test application."""
        yield Header(name="Myrient Settings Test", show_clock=True)
        with Container():
            yield MyrientSettingsScreen(settings=self.settings)
        yield Footer()


if __name__ == "__main__":
    app = SettingsTestApp()
    app.run()
