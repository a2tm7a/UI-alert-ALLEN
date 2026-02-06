"""
Validators Package
Provides modular validation rules for scraped course data.
"""

from .base_validator import BaseValidator, ValidationResult
from .broken_link_validator import BrokenLinkValidator
from .price_mismatch_validator import PriceMismatchValidator

__all__ = [
    'BaseValidator',
    'ValidationResult',
    'BrokenLinkValidator',
    'PriceMismatchValidator'
]
