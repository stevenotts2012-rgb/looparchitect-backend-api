"""Auto-discovery and registration of FastAPI routers."""

from fastapi import FastAPI, APIRouter
import pkgutil
import importlib
import logging

logger = logging.getLogger(__name__)


# Mapping of module names to their route configuration
# This ensures consistent prefixes and tags across entry points
ROUTE_CONFIG = {
    "health": {"prefix": "/api/v1", "tags": ["health"]},
    "db_health": {"prefix": "/api/v1", "tags": ["database"]},
    "api": {"prefix": "/api/v1", "tags": ["api"]},
    "loops": {"prefix": "/api/v1", "tags": ["loops"]},
    "loop_analysis": {"prefix": "/api/v1", "tags": ["loop_analysis"]},
    "audio": {"prefix": "/api/v1", "tags": ["audio"]},
    "render": {"prefix": "/api/v1", "tags": ["render"]},
    "render_jobs": {"prefix": "/api/v1", "tags": ["jobs"]},
    "arrange": {"prefix": "/api/v1", "tags": ["arrange"]},
    "arrangements": {"prefix": "/api/v1/arrangements", "tags": ["arrangements"]},
    "reference": {"prefix": "/api/v1/reference", "tags": ["reference"]},
    "styles": {"prefix": "/api/v1", "tags": ["styles"]},
    "track_quality": {"prefix": "/api/v1/track", "tags": ["track_quality"]},
}


def register_routers(app: FastAPI) -> None:
    """
    Auto-discovers and registers all APIRouter instances from app.routes modules.
    
    Scans all Python modules in the app.routes package, imports them,
    and includes any 'router' attribute that is an APIRouter instance.
    Applies appropriate prefixes and tags based on ROUTE_CONFIG.
    
    Args:
        app: The FastAPI application instance to register routers with
    """
    package = __name__
    registered_count = 0
    
    for module_info in pkgutil.iter_modules(__path__):
        # Skip sub-packages
        if module_info.ispkg:
            continue
        
        module_name = f"{package}.{module_info.name}"
        try:
            # Import the module
            module = importlib.import_module(module_name)
            
            # Check if it has a router attribute
            router = getattr(module, "router", None)
            
            if isinstance(router, APIRouter):
                # Get configuration for this module (if defined)
                config = ROUTE_CONFIG.get(module_info.name, {})
                
                # Register with prefix and tags
                app.include_router(
                    router,
                    prefix=config.get("prefix", ""),
                    tags=config.get("tags", [module_info.name])
                )
                registered_count += 1
                logger.info(
                    f"✅ Registered router from {module_info.name} "
                    f"(prefix={config.get('prefix', 'none')}, tags={config.get('tags', [module_info.name])})"
                )
            else:
                logger.debug(f"⏭️  Skipped {module_info.name} (no router found)")
                
        except Exception as e:
            logger.error(f"❌ Failed to import {module_name}: {e}")
    
    logger.info(f"📦 Registered {registered_count} routers from app.routes")
