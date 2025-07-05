# core/__init__.py

"""
Core services and models for the Telegram bot project.

This package exposes:
- CryptoHandler: handles TRC20 operations via tronpy
- DynamicPriceProvider: provides dynamic pricing logic
- BlockchainClient: interacts with Tron network (verify and transfer)
- Model, MODELS: domain model definitions
"""

# Core service classes
from .crypto_handler import CryptoHandler
from .price_provider import DynamicPriceProvider
from .blockchain_client import BlockchainClient

# Domain models
from .models import Model, MODELS

# Public API
__all__ = [
    "CryptoHandler",
    "DynamicPriceProvider",
    "BlockchainClient",
    "Model",
    "MODELS",
]
