"""Task-scoped authorization package for FastMCP with OpenFGA."""

from task_authz.config import FGAConfig, ResourceType, authz_namespace
from task_authz.middleware import OpenFGAPermissionMiddleware

__all__ = [
    "OpenFGAPermissionMiddleware",
    "FGAConfig",
    "ResourceType",
    "authz_namespace",
]
