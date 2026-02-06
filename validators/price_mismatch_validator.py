"""
Price Mismatch Validator
Validates that prices on course cards match the prices on PDPs.
"""

import re
from typing import Dict, List, Any
from .base_validator import BaseValidator, ValidationResult


class PriceMismatchValidator(BaseValidator):
    """
    Validates that the price shown on a course card matches the price on the PDP.
    
    A price mismatch occurs when:
    1. Both card and PDP have prices, but they differ numerically
    2. Card has a price but PDP doesn't (or vice versa)
    """
    
    def _validate(self, course_data: Dict[str, Any]) -> List[ValidationResult]:
        issues = []
        
        course_name = course_data.get('course_name', 'Unknown Course')
        card_price = course_data.get('price', '')
        pdp_price = course_data.get('pdp_price', '')
        price_mismatch_flag = course_data.get('price_mismatch', 0)
        
        # Skip validation if both prices are missing
        if self._is_price_missing(card_price) and self._is_price_missing(pdp_price):
            return issues
        
        # Check 1: Explicit mismatch flag from scraper
        if price_mismatch_flag == 1:
            issues.append(ValidationResult(
                type='PRICE_MISMATCH',
                severity='MEDIUM',
                message=f"Price on card doesn't match price on PDP",
                course_name=course_name,
                field='price',
                expected=card_price,
                actual=pdp_price
            ))
        
        # Check 2: Card has price but PDP doesn't
        elif not self._is_price_missing(card_price) and self._is_price_missing(pdp_price):
            issues.append(ValidationResult(
                type='PRICE_MISMATCH',
                severity='MEDIUM',
                message=f"Price shown on card but not found on PDP",
                course_name=course_name,
                field='pdp_price',
                expected=card_price,
                actual='Not Found'
            ))
        
        # Check 3: PDP has price but card doesn't
        elif self._is_price_missing(card_price) and not self._is_price_missing(pdp_price):
            issues.append(ValidationResult(
                type='PRICE_MISMATCH',
                severity='LOW',
                message=f"Price found on PDP but not shown on card",
                course_name=course_name,
                field='price',
                expected=pdp_price,
                actual='N/A'
            ))
        
        # Check 4: Both have prices but they differ (double-check with clean comparison)
        elif not price_mismatch_flag:
            clean_card = self._clean_price(card_price)
            clean_pdp = self._clean_price(pdp_price)
            
            if clean_card and clean_pdp and clean_card != clean_pdp:
                issues.append(ValidationResult(
                    type='PRICE_MISMATCH',
                    severity='MEDIUM',
                    message=f"Numeric price values don't match",
                    course_name=course_name,
                    field='price',
                    expected=f"{card_price} ({clean_card})",
                    actual=f"{pdp_price} ({clean_pdp})"
                ))
        
        return issues
    
    def _is_price_missing(self, price: str) -> bool:
        """Check if a price value is missing or invalid."""
        if not price:
            return True
        price_lower = price.lower()
        return price_lower in ['n/a', 'not found', 'error', '']
    
    def _clean_price(self, price_str: str) -> str:
        """
        Extract numeric value from price strings for comparison.
        E.g., '₹ 93,500' -> '93500'
        """
        if self._is_price_missing(price_str):
            return None
        # Extract only digits
        nums = "".join(re.findall(r'\d+', price_str.replace(',', '')))
        return nums if nums else None
