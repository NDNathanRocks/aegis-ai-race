# Cloud Infrastructure SOP — Backup and Data Retention (v1.6)

## 1. Backup schedule
Production databases are backed up with a full snapshot nightly at 01:00 UTC and with continuous transaction log shipping every five minutes. Object storage buckets use versioning with a 30-day noncurrent-version lifecycle. Configuration repositories are mirrored to a second region.

## 2. Retention periods
- Daily snapshots: 35 days.
- Monthly snapshots: 13 months.
- Audit logs: 7 years in write-once storage.
- Application logs: 90 days online, then archived for one year.
Retention may be extended by a legal hold issued by the General Counsel.

## 3. Restore testing
Restore tests are performed quarterly on a rotating sample of systems. A restore test passes when the recovery point objective of 15 minutes and the recovery time objective of 4 hours are both met. Failures are logged as P2 tickets.

## 4. Encryption and access
Backups are encrypted with keys held in the managed key service. Restore operations require two-person approval for Tier A systems. Access to backup storage is reviewed monthly.

## 5. Deletion
When retention ends, data is deleted automatically and a deletion certificate is stored. Deletion of data under a legal hold is blocked until the hold is released.

*Demo knowledge base; not legal, tax or medical advice.*
