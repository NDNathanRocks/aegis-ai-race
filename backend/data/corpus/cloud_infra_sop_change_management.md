# Cloud Infrastructure SOP — Change Management (v3.4)

## 1. Change Types
- Standard: pre-approved, low risk (certificate rotation, scaling within limits).
- Normal: requires peer review and CAB approval; scheduled in the weekly maintenance window (Tuesday 02:00-04:00 UTC).
- Emergency: only to restore service for a P1; requires incident commander approval and a retroactive review within 2 business days.

## 2. Requirements
2.1 Every Normal change needs a rollback plan tested in staging.
2.2 Customers must be notified at least 72 hours before scheduled maintenance that may affect availability.
2.3 Changes are frozen from December 15 to January 5 except Emergency changes.

## 3. Post-Change Verification
After deployment, verify health checks for 30 minutes. If error rate exceeds 2% above baseline, roll back automatically.
