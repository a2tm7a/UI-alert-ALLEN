"""
Broken Link Validator
Validates that course cards actually lead to a different PDP page.
"""

from typing import Dict, List, Any
from .base_validator import BaseValidator, ValidationResult


class BrokenLinkValidator(BaseValidator):
    """
    Validates that the CTA link from a course card leads to a valid PDP.
    
    A link is considered broken if:
    1. The CTA link is the same as the base URL (didn't navigate)
    2. The is_broken flag is set to 1
    3. The CTA link is missing or invalid
    """
    
    def _validate(self, course_data: Dict[str, Any]) -> List[ValidationResult]:
        issues = []
        
        course_name = course_data.get('course_name', 'Unknown Course')
        base_url = course_data.get('base_url', '')
        cta_link = course_data.get('cta_link', '')
        is_broken = course_data.get('is_broken', 0)
        
        # Check 1: CTA link same as base URL
        if cta_link and base_url and cta_link.strip('/') == base_url.strip('/'):
            issues.append(ValidationResult(
                type='BROKEN_LINK',
                severity='HIGH',
                message=f"Course card doesn't navigate to a new page",
                course_name=course_name,
                field='cta_link',
                expected='Different URL from base',
                actual=cta_link
            ))
        
        # Check 2: Explicit broken flag
        elif is_broken == 1:
            issues.append(ValidationResult(
                type='BROKEN_LINK',
                severity='HIGH',
                message=f"Link verification failed during scraping",
                course_name=course_name,
                field='cta_link',
                expected='Valid navigation',
                actual=cta_link
            ))
        
        # Check 3: Missing or invalid CTA link
        elif not cta_link or cta_link in ['N/A', 'Error', '']:
            issues.append(ValidationResult(
                type='BROKEN_LINK',
                severity='CRITICAL',
                message=f"No valid CTA link found on course card",
                course_name=course_name,
                field='cta_link',
                expected='Valid URL',
                actual=cta_link or 'None'
            ))
        
        return issues
