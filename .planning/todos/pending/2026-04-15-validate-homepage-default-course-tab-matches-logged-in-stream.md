---
created: 2026-04-15T18:28:01.337Z
title: Validate homepage default course tab matches logged-in stream
area: auth
files:
  - scraper.py:482-608
  - config/urls.yaml:51-53
---

## Problem

When a user is logged in with a specific stream (e.g. JEE, NEET, Class 6-10), the homepage (`https://allen.in/`) shows a "Courses" section with multiple stream tabs. The default active tab should automatically match the stream of the logged-in profile.

Currently there is no assertion in the authenticated validation pass that checks which tab is active/selected on the homepage courses section. A regression could silently serve the wrong stream's courses to a logged-in user without any test catching it.

## Solution

In the authenticated scraping/validation pass for the HOME section, after navigating to `https://allen.in/`:
1. Detect the active tab in the courses section (e.g. by checking for an `aria-selected="true"` or active class on the tab element).
2. Assert that the active tab text matches the expected stream for the current auth session (e.g. "JEE" tab active for a JEE-11th session).
3. Report a failure if the default tab does not match, surfacing it in the validation results and the HTML report.
