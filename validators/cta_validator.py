"""
CTA Validator
Validates that a course card's purchase flow is fully functional:
  1. The CTA link on the card leads to a valid, different PDP page
  2. The PDP has an "Enroll Now" / "Buy Now" button visible

Both checks represent the same business failure: a user cannot purchase the course.
"""

from typing import Dict, List, Any
from .base_validator import BaseValidator, ValidationResult


class CTAValidator(BaseValidator):
    """
    Unified validator for the course purchase flow.

    A course fails if:
    - The CTA link is missing or doesn't navigate to a new page  (CRITICAL)
    - The PDP was reached but has no purchase button             (HIGH)
    """

    def _validate(self, course_data: Dict[str, Any]) -> List[ValidationResult]:
        issues = []

        course_name = course_data.get('course_name', 'Unknown Course')
        base_url    = course_data.get('base_url', '')
        cta_link    = course_data.get('cta_link', '')
        is_broken   = course_data.get('is_broken', 0)
        cta_status  = course_data.get('cta_status', 'N/A')

        # --- Check 1: CTA link missing or invalid ---
        if not cta_link or cta_link in ['N/A', 'Error', '']:
            issues.append(ValidationResult(
                type='CTA_BROKEN',
                severity='CRITICAL',
                message="No CTA link found on course card",
                course_name=course_name,
                field='cta_link',
                expected='Valid URL',
                actual=cta_link or 'None'
            ))
            return issues  # No point checking further

        # --- Check 2: Link doesn't navigate away from the listing ---
        link_is_same_page = (
            is_broken == 1 or
            (base_url and cta_link.strip('/') == base_url.strip('/'))
        )
        if link_is_same_page:
            issues.append(ValidationResult(
                type='CTA_BROKEN',
                severity='CRITICAL',
                message="Course card link doesn't navigate to a PDP",
                course_name=course_name,
                field='cta_link',
                expected='Different URL from listing page',
                actual=cta_link
            ))
            return issues  # PDP unreachable, CTA check is moot

        # --- Check 3: PDP reached but no purchase button ---
        if cta_status == 'Not Found':
            issues.append(ValidationResult(
                type='CTA_MISSING',
                severity='HIGH',
                message="PDP reachable but no Enroll/Buy Now button found",
                course_name=course_name,
                field='cta_status',
                expected='Enroll Now / Buy Now button',
                actual='Not Found'
            ))

        return issues
