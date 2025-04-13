from .manager import auth_manager
from .routes import auth_bp

# Export the auth manager and blueprint
__all__ = ['auth_manager', 'auth_bp']
