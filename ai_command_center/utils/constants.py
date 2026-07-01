HIGH_RISK_ACTIONS = ["delete", "submit", "cancel", "amend", "payment", "journal_entry", "bulk_update"]
MEDIUM_RISK_ACTIONS = ["create", "update", "export", "email"]
LOW_RISK_ACTIONS = ["read", "list", "report", "dashboard"]

BLOCKED_DOCTYPES_BY_DEFAULT = [
    "User", "Role", "Has Role", "DocPerm", "Custom DocPerm", "Module Def",
    "Installed Applications", "System Settings", "Singles", "DocType", "Patch Log",
    "Error Log", "Access Log", "Activity Log",
]

SENSITIVE_FIELD_KEYWORDS = [
    "password", "secret", "api_key", "api_secret", "token", "otp", "salary",
    "bank", "account_no", "pan", "aadhaar",
]

TECHNICAL_FIELDS = {"owner", "modified_by", "creation", "modified", "docstatus", "idx"}
ALLOWED_FILTER_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "in", "not in", "like", "between"}
MAX_LIST_LIMIT = 500
