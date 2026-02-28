"""
Validators Package
Provides modular validation rules for scraped course data.
"""

from .base_validator import BaseValidator, ValidationResult
from .cta_validator import CTAValidator
from .price_mismatch_validator import PriceMismatchValidator

__all__ = [
    'BaseValidator',
    'ValidationResult',
    'CTAValidator',
    'PriceMismatchValidator',
]
