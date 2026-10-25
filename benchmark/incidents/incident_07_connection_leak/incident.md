# Incident Alert: Database connection pool exhaustion under regular traffic
**Time Started:** 22:50 UTC
**Affected Endpoint:** GET /products/{id}
**Severity:** Critical
**Symptoms:** After several dozen requests, the API hangs and reports connection pool timeout errors on all database queries.
