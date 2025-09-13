#https://docs.pydantic.dev/latest/concepts/pydantic_settings/#usage
import os
from pathlib import Path
from typing import List, Optional

from pydantic import (
    BaseModel,
    Field,
    field_validator,
)

from pydantic_settings import BaseSettings, SettingsConfigDict


class DownloadSettings(BaseModel):
    """Settings for download behavior and retry logic."""
    max_retries: int = Field(default=3, description="Maximum number of download retry attempts")
    retry_delay: int = Field(default=5, description="Delay in seconds between retry attempts")
    show_progress: bool = Field(default=True, description="Whether to show download progress bar")


class FilterSettings(BaseModel):
    """Settings for filtering ROM files."""
    include_patterns: List[str] = Field(
        default=['%28USA%29'], 
        description="Patterns that must be present in ROM filenames"
    )
    exclude_patterns: List[str] = Field(
        default=['%28Demo%29', '%28Beta%29'], 
        description="Patterns to exclude from ROM filenames"
    )
    
    @field_validator('include_patterns', 'exclude_patterns')
    def validate_patterns(cls, v):
        if not isinstance(v, list):
            raise ValueError('Patterns must be a list')
        return v


class Settings(BaseSettings):
    """Main settings class for Myrient ROM scraper."""
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        env_prefix='MYRIENT_'
    )
    
    # Base URL settings
    base_url: str = Field(
        default='https://myrient.erista.me',
        description="Base URL for Myrient website"
    )
    
    # Specific console/system path
    console_path: str = Field(
        default='/files/No-Intro/Nintendo%20-%20Game%20Boy/',
        description="Path to specific console ROM collection"
    )
    
    # Download directory settings
    download_directory: Optional[str] = Field(
        default="./",
        description="Directory to download ROMs to. If None, uses current working directory"
    )
    
    # Nested settings
    download: DownloadSettings = Field(default_factory=DownloadSettings)
    filters: FilterSettings = Field(default_factory=FilterSettings)
    
    # HTTP settings
    user_agent: str = Field(
        default='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        description="User agent string for HTTP requests"
    )
    
    timeout: int = Field(
        default=30,
        description="HTTP request timeout in seconds"
    )
    
    # Logging settings
    log_level: str = Field(
        default='INFO',
        description="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )
    
    verbose: bool = Field(
        default=True,
        description="Enable verbose output"
    )
    
    @property
    def full_url(self) -> str:
        """Get the complete URL for the console ROM collection."""
        return f"{self.base_url.rstrip('/')}{self.console_path}"
    
    @property
    def effective_download_directory(self) -> str:
        """Get the effective download directory, defaulting to current working directory."""
        if self.download_directory:
            return str(Path(self.download_directory).resolve())
        return os.getcwd()
    
    @field_validator('base_url')
    def validate_base_url(cls, v):
        if not v.startswith(('http://', 'https://')):
            raise ValueError('Base URL must start with http:// or https://')
        return v.rstrip('/')
    
    @field_validator('console_path')
    def validate_console_path(cls, v):
        if not v.startswith('/'):
            v = '/' + v
        return v
    
    @field_validator('log_level')
    def validate_log_level(cls, v):
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f'Log level must be one of: {valid_levels}')
        return v.upper()
    
    def should_download_file(self, filename: str) -> bool:
        """
        Check if a file should be downloaded based on filter settings.
        
        Args:
            filename: The filename to check
            
        Returns:
            bool: True if file should be downloaded, False otherwise
        """
        # Check if any include patterns are present
        if self.filters.include_patterns:
            has_include = any(pattern in filename for pattern in self.filters.include_patterns)
            if not has_include:
                return False
        
        # Check if any exclude patterns are present
        if self.filters.exclude_patterns:
            has_exclude = any(pattern in filename for pattern in self.filters.exclude_patterns)
            if has_exclude:
                return False
        
        return True
    
    def get_local_filepath(self, filename: str) -> str:
        """
        Get the full local file path for a given filename.
        
        Args:
            filename: The filename to get the path for
            
        Returns:
            str: Full local file path
        """
        return os.path.join(self.effective_download_directory, filename)
    
    def save(self):
        #TODO save settings to a file type
        self.model_dump_json()