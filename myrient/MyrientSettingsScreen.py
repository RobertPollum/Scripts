from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Button, Label, Input, Switch, TextArea, Static, 
    Collapsible, Select
)
from textual.widget import Widget
from textual.validation import Number, ValidationResult, Validator
from typing import Optional
import os

from MyrientSettings import Settings


class URLValidator(Validator):
    """Validator for URL fields."""
    
    def validate(self, value: str) -> ValidationResult:
        if not value:
            return self.failure("URL cannot be empty")
        if not value.startswith(('http://', 'https://')):
            return self.failure("URL must start with http:// or https://")
        return self.success()


class PathValidator(Validator):
    """Validator for path fields."""
    
    def validate(self, value: str) -> ValidationResult:
        if not value:
            return self.failure("Path cannot be empty")
        if not value.startswith('/'):
            return self.failure("Path must start with /")
        return self.success()


class LogLevelValidator(Validator):
    """Validator for log level fields."""
    
    def validate(self, value: str) -> ValidationResult:
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if value.upper() not in valid_levels:
            return self.failure(f"Log level must be one of: {', '.join(valid_levels)}")
        return self.success()


class MyrientSettingsScreen(Widget):
    """Interactive settings screen for Myrient Navigator."""
    CSS_PATH="MyrientSettingsScreen.tcss"
    
    def __init__(self, settings: Optional[Settings] = None, **kwargs):
        super().__init__(**kwargs)
        self.settings = settings or Settings()
        self._original_settings = self.settings.model_copy()
        
    def compose(self) -> ComposeResult:
        """Compose the settings screen layout."""
        with ScrollableContainer(id="settings-scroll"):
            yield Static("Myrient Settings", classes="settings-title")
            
            # Basic Settings Section
            with Collapsible(title="Basic Settings", collapsed=False):
                with Vertical(classes="settings-section"):
                    yield Label("Base URL:")
                    yield Input(
                        value=self.settings.base_url,
                        placeholder="https://myrient.erista.me",
                        validators=[URLValidator()],
                        id="base-url-input"
                    )
                    
                    yield Label("Console Path:")
                    yield Input(
                        value=self.settings.console_path,
                        placeholder="/files/No-Intro/Nintendo%20-%20Game%20Boy/",
                        validators=[PathValidator()],
                        id="console-path-input"
                    )
                    
                    yield Label("Download Directory:")
                    yield Input(
                        value=self.settings.download_directory or "./",
                        placeholder="./downloads",
                        id="download-directory-input"
                    )
                    yield Button("Browse...", id="browse-directory", variant="default")
            
            # Download Settings Section
            with Collapsible(title="Download Settings", collapsed=True):
                with Vertical(classes="settings-section"):
                    yield Label("Max Retries:")
                    yield Input(
                        value=str(self.settings.download.max_retries),
                        validators=[Number(minimum=0, maximum=10)],
                        id="max-retries-input"
                    )
                    
                    yield Label("Retry Delay (seconds):")
                    yield Input(
                        value=str(self.settings.download.retry_delay),
                        validators=[Number(minimum=0, maximum=60)],
                        id="retry-delay-input"
                    )
                    
                    with Horizontal():
                        yield Label("Show Progress Bar:")
                        yield Switch(
                            value=self.settings.download.show_progress,
                            id="show-progress-switch"
                        )
            
            # Filter Settings Section
            with Collapsible(title="Filter Settings", collapsed=True):
                with Vertical(classes="settings-section"):
                    yield Label("Include Patterns (one per line):")
                    yield TextArea(
                        text="\n".join(self.settings.filters.include_patterns),
                        id="include-patterns-textarea"
                    )
                    
                    yield Label("Exclude Patterns (one per line):")
                    yield TextArea(
                        text="\n".join(self.settings.filters.exclude_patterns),
                        id="exclude-patterns-textarea"
                    )
                    
                    yield Static(
                        "Note: Patterns use URL encoding (e.g., %28 = '(', %29 = ')')",
                        classes="help-text"
                    )
            
            # HTTP Settings Section
            with Collapsible(title="HTTP Settings", collapsed=True):
                with Vertical(classes="settings-section"):
                    yield Label("User Agent:")
                    yield Input(
                        value=self.settings.user_agent,
                        id="user-agent-input"
                    )
                    
                    yield Label("Timeout (seconds):")
                    yield Input(
                        value=str(self.settings.timeout),
                        validators=[Number(minimum=1, maximum=300)],
                        id="timeout-input"
                    )
            
            # Logging Settings Section
            with Collapsible(title="Logging Settings", collapsed=True):
                with Vertical(classes="settings-section"):
                    yield Label("Log Level:")
                    yield Select(
                        options=[
                            ("DEBUG", "DEBUG"),
                            ("INFO", "INFO"),
                            ("WARNING", "WARNING"),
                            ("ERROR", "ERROR"),
                            ("CRITICAL", "CRITICAL")
                        ],
                        value=self.settings.log_level,
                        id="log-level-select"
                    )
                    
                    with Horizontal():
                        yield Label("Verbose Output:")
                        yield Switch(
                            value=self.settings.verbose,
                            id="verbose-switch"
                        )
            
            # Action Buttons
            with Horizontal(classes="action-buttons"):
                yield Button("Save Settings", id="save-settings-btn", variant="primary")
                yield Button("Reset to Defaults", id="reset-settings-btn", variant="warning")
                yield Button("Load from File", id="load-settings-btn", variant="default")
                yield Button("Cancel", id="cancel-settings-btn", variant="default")
            
            # Status message
            yield Static("", id="settings-status", classes="status-message")
    
    @on(Button.Pressed, "#browse-directory")
    def browse_directory(self, event: Button.Pressed) -> None:
        """Open directory browser."""
        # For now, we'll use a simple input. In a full implementation,
        # you might want to integrate with a file dialog or directory tree
        current_dir = self.query_one("#download-directory-input", Input).value
        if os.path.exists(current_dir):
            self.show_status(f"Current directory: {os.path.abspath(current_dir)}")
        else:
            self.show_status("Directory does not exist", error=True)
    
    @on(Button.Pressed, "#save-settings-btn")
    def save_settings(self, event: Button.Pressed) -> None:
        """Save the current settings."""
        try:
            # Collect all values from inputs
            updated_settings = self._collect_settings_from_inputs()
            
            # Validate the settings
            validated_settings = Settings(**updated_settings)
            
            # Save to file
            validated_settings.save()
            
            # Update our internal settings
            self.settings = validated_settings
            self._original_settings = validated_settings.model_copy()
            
            self.show_status("Settings saved successfully!")
            
        except Exception as e:
            self.show_status(f"Error saving settings: {str(e)}", error=True)
    
    @on(Button.Pressed, "#reset-settings-btn")
    def reset_settings(self, event: Button.Pressed) -> None:
        """Reset settings to defaults."""
        try:
            default_settings = Settings()
            self._populate_inputs_from_settings(default_settings)
            self.show_status("Settings reset to defaults")
        except Exception as e:
            self.show_status(f"Error resetting settings: {str(e)}", error=True)
    
    @on(Button.Pressed, "#load-settings-btn")
    def load_settings(self, event: Button.Pressed) -> None:
        """Load settings from file."""
        try:
            loaded_settings = Settings.load_from_file()
            self._populate_inputs_from_settings(loaded_settings)
            self.settings = loaded_settings
            self.show_status("Settings loaded from file")
        except FileNotFoundError:
            self.show_status("No settings file found", error=True)
        except ValueError as e:
            self.show_status(f"Error loading settings: {str(e)}", error=True)
        except Exception as e:
            self.show_status(f"Unexpected error loading settings: {str(e)}", error=True)
    
    @on(Button.Pressed, "#cancel-settings-btn")
    def cancel_settings(self, event: Button.Pressed) -> None:
        """Cancel changes and revert to original settings."""
        self._populate_inputs_from_settings(self._original_settings)
        self.settings = self._original_settings.model_copy()
        self.show_status("Changes cancelled")
    
    def _collect_settings_from_inputs(self) -> dict:
        """Collect all settings values from input widgets."""
        # Basic settings
        base_url = self.query_one("#base-url-input", Input).value
        console_path = self.query_one("#console-path-input", Input).value
        download_directory = self.query_one("#download-directory-input", Input).value
        
        # Download settings
        max_retries = int(self.query_one("#max-retries-input", Input).value or "3")
        retry_delay = int(self.query_one("#retry-delay-input", Input).value or "5")
        show_progress = self.query_one("#show-progress-switch", Switch).value
        
        # Filter settings
        include_patterns_text = self.query_one("#include-patterns-textarea", TextArea).text
        exclude_patterns_text = self.query_one("#exclude-patterns-textarea", TextArea).text
        
        include_patterns = [p.strip() for p in include_patterns_text.split('\n') if p.strip()]
        exclude_patterns = [p.strip() for p in exclude_patterns_text.split('\n') if p.strip()]
        
        # HTTP settings
        user_agent = self.query_one("#user-agent-input", Input).value
        timeout = int(self.query_one("#timeout-input", Input).value or "30")
        
        # Logging settings
        log_level = self.query_one("#log-level-select", Select).value
        verbose = self.query_one("#verbose-switch", Switch).value
        
        return {
            "base_url": base_url,
            "console_path": console_path,
            "download_directory": download_directory,
            "download": {
                "max_retries": max_retries,
                "retry_delay": retry_delay,
                "show_progress": show_progress
            },
            "filters": {
                "include_patterns": include_patterns,
                "exclude_patterns": exclude_patterns
            },
            "user_agent": user_agent,
            "timeout": timeout,
            "log_level": log_level,
            "verbose": verbose
        }
    
    def _populate_inputs_from_settings(self, settings: Settings) -> None:
        """Populate input widgets with values from settings."""
        # Basic settings
        self.query_one("#base-url-input", Input).value = settings.base_url
        self.query_one("#console-path-input", Input).value = settings.console_path
        self.query_one("#download-directory-input", Input).value = settings.download_directory or "./"
        
        # Download settings
        self.query_one("#max-retries-input", Input).value = str(settings.download.max_retries)
        self.query_one("#retry-delay-input", Input).value = str(settings.download.retry_delay)
        self.query_one("#show-progress-switch", Switch).value = settings.download.show_progress
        
        # Filter settings
        self.query_one("#include-patterns-textarea", TextArea).text = "\n".join(settings.filters.include_patterns)
        self.query_one("#exclude-patterns-textarea", TextArea).text = "\n".join(settings.filters.exclude_patterns)
        
        # HTTP settings
        self.query_one("#user-agent-input", Input).value = settings.user_agent
        self.query_one("#timeout-input", Input).value = str(settings.timeout)
        
        # Logging settings
        self.query_one("#log-level-select", Select).value = settings.log_level
        self.query_one("#verbose-switch", Switch).value = settings.verbose
    
    def show_status(self, message: str, error: bool = False) -> None:
        """Show a status message."""
        status_widget = self.query_one("#settings-status", Static)
        status_widget.update(message)
        if error:
            status_widget.add_class("error")
        else:
            status_widget.remove_class("error")
    
    def get_settings(self) -> Settings:
        """Get the current settings object."""
        return self.settings
    
    def update_settings(self, settings: Settings) -> None:
        """Update the settings and refresh the UI."""
        self.settings = settings
        self._original_settings = settings.model_copy()
        self._populate_inputs_from_settings(settings)
