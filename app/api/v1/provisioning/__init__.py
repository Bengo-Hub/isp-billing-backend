"""
Main provisioning router that combines all provisioning modules.
This replaces the monolithic provisioning.py with a modular approach.
"""
import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

# Import and include all provisioning sub-routers
from . import bootstrap
from . import network
from . import workflow
from . import stream
from . import device_scan
from . import token

# Include all provisioning sub-routers
router.include_router(bootstrap.router, prefix="/bootstrap", tags=["bootstrap"])
router.include_router(network.router, prefix="/network", tags=["network"])
router.include_router(workflow.router, prefix="", tags=["workflow"])
router.include_router(stream.router, prefix="", tags=["stream"])
router.include_router(device_scan.router, prefix="/device", tags=["device-scan"])
router.include_router(token.router, prefix="/token", tags=["token"])

