# Myrient Settings Screen

This document describes the interactive settings screen for the Myrient Navigator application.

## Overview

The `MyrientSettingsScreen` class provides a comprehensive, interactive interface for editing all Myrient Navigator settings using the Textual library. It integrates seamlessly with the existing `MyrientSettings.py` module for loading, validating, and saving settings.

## Features

### Settings Categories

The settings screen is organized into collapsible sections:

1. **Basic Settings**
   - Base URL: The main Myrient website URL
   - Console Path: Path to specific console ROM collection
   - Download Directory: Local directory for downloads

2. **Download Settings**
   - Max Retries: Maximum number of download retry attempts (0-10)
   - Retry Delay: Delay in seconds between retry attempts (0-60)
   - Show Progress Bar: Toggle for download progress display

3. **Filter Settings**
   - Include Patterns: Patterns that must be present in ROM filenames
   - Exclude Patterns: Patterns to exclude from ROM filenames
   - Note: Patterns use URL encoding (%28 = '(', %29 = ')')

4. **HTTP Settings**
   - User Agent: HTTP user agent string for requests
   - Timeout: HTTP request timeout in seconds (1-300)

5. **Logging Settings**
   - Log Level: Logging verbosity (DEBUG, INFO, WARNING, ERROR, CRITICAL)
   - Verbose Output: Toggle for verbose console output

### Input Validation

The settings screen includes comprehensive validation:

- **URL Validation**: Ensures URLs start with http:// or https://
- **Path Validation**: Ensures paths start with /
- **Number Validation**: Validates numeric inputs within appropriate ranges
- **Log Level Validation**: Ensures log level is one of the valid options

### Action Buttons

- **Save Settings**: Validates and saves current settings to file
- **Reset to Defaults**: Resets all settings to their default values
- **Load from File**: Loads settings from existing settings.json file
- **Cancel**: Reverts all changes to the last saved state

## Usage

### Integration with Main Navigator

The settings screen is integrated into the main `MyrientNavigator` application:

```python
from MyrientSettingsScreen import MyrientSettingsScreen

# In your compose method:
self.settings_screen = MyrientSettingsScreen(settings=self.settings, id="settings-screen")
yield self.settings_screen
```

### Standalone Usage

You can also run the settings screen standalone for testing:

```bash
python test_settings_screen.py
```

### Programmatic Usage

```python
from MyrientSettings import Settings
from MyrientSettingsScreen import MyrientSettingsScreen

# Create settings screen with existing settings
settings = Settings()
settings_screen = MyrientSettingsScreen(settings=settings)

# Get updated settings after user interaction
updated_settings = settings_screen.get_settings()

# Update settings programmatically
new_settings = Settings(base_url="https://example.com")
settings_screen.update_settings(new_settings)
```

## File Structure

- `MyrientSettingsScreen.py`: Main settings screen implementation
- `MyrientSettings.py`: Settings data models and validation
- `test_settings_screen.py`: Standalone test application
- `MyrientNavigator.tcss`: CSS styles for the settings screen

## Settings File Format

Settings are saved to `settings.json` in JSON format:

```json
{
    "base_url": "https://myrient.erista.me",
    "console_path": "/files/No-Intro/Nintendo%20-%20Game%20Boy/",
    "download_directory": "./downloads",
    "download": {
        "max_retries": 3,
        "retry_delay": 5,
        "show_progress": true
    },
    "filters": {
        "include_patterns": ["%28USA%29"],
        "exclude_patterns": ["%28Demo%29", "%28Beta%29"]
    },
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "timeout": 30,
    "log_level": "INFO",
    "verbose": true
}
```

## Error Handling

The settings screen provides user-friendly error messages for:

- Invalid input values
- File I/O errors
- Validation failures
- Missing dependencies

Error messages are displayed in the status area at the bottom of the screen.

## Keyboard Shortcuts

When running the test application:

- `d`: Toggle dark mode
- `q`: Quit application
- `Tab`: Navigate between input fields
- `Enter`: Activate buttons
- `Space`: Toggle switches

## Dependencies

- `textual`: TUI framework
- `pydantic`: Data validation and settings management
- `pydantic-settings`: Settings management extensions

## Customization

The settings screen can be customized by:

1. Modifying the CSS styles in `MyrientNavigator.tcss`
2. Adding new validators in `MyrientSettingsScreen.py`
3. Extending the settings model in `MyrientSettings.py`
4. Adding new input widgets for additional settings

## Troubleshooting

### Common Issues

1. **Settings not saving**: Check file permissions in the current directory
2. **Validation errors**: Ensure all required fields are filled correctly
3. **Import errors**: Verify all dependencies are installed
4. **Display issues**: Check terminal size and color support

### Debug Mode

Run with debug logging to troubleshoot issues:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Contributing

When adding new settings:

1. Add the setting to the appropriate model in `MyrientSettings.py`
2. Add the corresponding input widget in `MyrientSettingsScreen.py`
3. Update the `_collect_settings_from_inputs()` method
4. Update the `_populate_inputs_from_settings()` method
5. Add appropriate validation if needed
6. Update this documentation
