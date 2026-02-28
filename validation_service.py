"""
Validation Service
Orchestrates validation rules and manages validation results.
"""

import sqlite3
import logging
from typing import List, Dict, Any
from validators import BaseValidator, ValidationResult, PurchaseCTAValidator, PriceMismatchValidator


class ValidationService:
    """
    Service class that manages validation workflow.
    Builds validator chains and processes validation results.
    """
    
    def __init__(self, db_name: str = "scraped_data.db"):
        self.db_name = db_name
        self.validator_chain = self._build_default_validator_chain()
        self.validation_results = []
    
    def _build_default_validator_chain(self) -> BaseValidator:
        """
        Build the default chain of validators.
        Can be overridden or configured externally in future phases.
        """
        cta = PurchaseCTAValidator()
        price_mismatch = PriceMismatchValidator()

        # CTA check runs first — if a course is completely unreachable,
        # we still want price mismatch checked independently.
        cta.set_next(price_mismatch)

        return cta
    
    def validate_course(self, course_data: Dict[str, Any]) -> List[ValidationResult]:
        """
        Validate a single course record.
        
        Args:
            course_data: Dictionary containing course information
            
        Returns:
            List of ValidationResult objects
        """
        return self.validator_chain.validate(course_data)
    
    def validate_all_courses(self) -> List[ValidationResult]:
        """
        Validate all courses in the database.
        
        Returns:
            List of all ValidationResult objects found
        """
        all_issues = []
        
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM courses")

            for row in cursor.fetchall():
                course_data = dict(row)
                issues = self.validate_course(course_data)
                # Stamp each result with the viewport from its DB row
                viewport = course_data.get('viewport', 'desktop')
                for issue in issues:
                    issue.viewport = viewport
                all_issues.extend(issues)
        
        self.validation_results = all_issues
        return all_issues
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of validation results.
        
        Returns:
            Dictionary with counts by type and severity
        """
        if not self.validation_results:
            return {
                'total_issues': 0,
                'by_type': {},
                'by_severity': {}
            }
        
        summary = {
            'total_issues': len(self.validation_results),
            'by_type': {},
            'by_severity': {}
        }
        
        for result in self.validation_results:
            # Count by type
            summary['by_type'][result.type] = summary['by_type'].get(result.type, 0) + 1
            
            # Count by severity
            summary['by_severity'][result.severity] = summary['by_severity'].get(result.severity, 0) + 1
        
        return summary
    
    def get_issues_by_severity(self, severity: str) -> List[ValidationResult]:
        """Get all issues of a specific severity level."""
        return [r for r in self.validation_results if r.severity == severity]
    
    def get_issues_by_type(self, issue_type: str) -> List[ValidationResult]:
        """Get all issues of a specific type."""
        return [r for r in self.validation_results if r.type == issue_type]
    
    def log_results(self):
        """Log validation results to the console."""
        if not self.validation_results:
            logging.info("✓ No validation issues found!")
            return
        
        summary = self.get_summary()
        
        logging.info("=" * 60)
        logging.info("VALIDATION REPORT")
        logging.info("=" * 60)
        logging.info(f"Total Issues Found: {summary['total_issues']}")
        logging.info("")
        
        # By Type
        logging.info("Issues by Type:")
        for issue_type, count in summary['by_type'].items():
            logging.info(f"  {issue_type}: {count}")
        logging.info("")
        
        # By Severity
        logging.info("Issues by Severity:")
        for severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
            count = summary['by_severity'].get(severity, 0)
            if count > 0:
                logging.warning(f"  {severity}: {count}")
        logging.info("")
        
        # Detailed Issues (Critical and High only)
        critical_and_high = [r for r in self.validation_results if r.severity in ['CRITICAL', 'HIGH']]
        if critical_and_high:
            logging.info("Critical & High Severity Issues:")
            for result in critical_and_high:
                logging.warning(f"  [{result.severity}] {result.course_name}")
                logging.warning(f"    {result.message}")
                if result.expected and result.actual:
                    logging.warning(f"    Expected: {result.expected}")
                    logging.warning(f"    Actual: {result.actual}")
        
        logging.info("=" * 60)
