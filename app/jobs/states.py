KIND_MENU_REPORT = "menu_report"

QUEUED = "queued"
RUNNING = "running"
RETRY_WAIT = "retry_wait"
SUCCEEDED = "succeeded"
FAILED = "failed"

STATUSES = (QUEUED, RUNNING, RETRY_WAIT, SUCCEEDED, FAILED)
TERMINAL = (SUCCEEDED, FAILED)

EVENT_EXECUTE = "job.execute"
EVENT_FAILED = "job.failed"

QUEUE_EXECUTE = "jobs.execute"
QUEUE_FAILED = "jobs.failed"

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ERR_EXECUTION = "execution_error"
ERR_INVALID_SNAPSHOT = "invalid_snapshot"
ERR_LEASE_EXPIRED = "lease_expired"
