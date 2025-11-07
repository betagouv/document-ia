"""Configuration utilities for the application."""

from pathlib import Path


class Config:
    """Application configuration."""
    
    # Project paths
    ROOT_DIR = Path(__file__).parent.parent.parent
    SRC_DIR = ROOT_DIR / "src"
    DATA_DIR = ROOT_DIR / "data"
    
    # App settings
    APP_TITLE = "Streamlit App"
    PAGE_ICON = "📊"
    LAYOUT = "wide"
    
    @classmethod
    def ensure_directories(cls):
        """Ensure necessary directories exist."""
        cls.DATA_DIR.mkdir(exist_ok=True)