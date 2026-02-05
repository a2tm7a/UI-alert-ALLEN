Backlog:
[x] Course cards CTA should work for homepage
[] Course cards CTA should work for category pages
[] Course cards CTA should work for PLP pages
[] Course cards price should match of PDPs
[] Sticky banners should be clickable

Architecture Note:
The codebase has been refactored into a modular Strategy Pattern (ScraperEngine + Specialized Handlers).
Verification logic now automatically visits each captured CTA URL to confirm PDP data (prices and enrollment buttons).
