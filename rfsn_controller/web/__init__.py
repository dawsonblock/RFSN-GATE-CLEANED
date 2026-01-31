"""RFSN Web UI package.

Provides a Gradio-based web interface for the RFSN controller.
"""

from __future__ import annotations

__all__ = ["create_app", "launch"]


def create_app():
    """Create the Gradio application."""
    from .app import create_demo
    return create_demo()


def launch(share: bool = False, server_port: int = 7860):
    """Launch the web UI.
    
    Args:
        share: If True, create a public URL via Gradio's sharing service
        server_port: Port to run the server on
    """
    app = create_app()
    app.launch(share=share, server_port=server_port)
