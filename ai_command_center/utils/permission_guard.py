import frappe

from ai_command_center.utils.constants import BLOCKED_DOCTYPES_BY_DEFAULT, HIGH_RISK_ACTIONS, LOW_RISK_ACTIONS, MEDIUM_RISK_ACTIONS
from ai_command_center.utils.field_filter import get_allowed_fields

ACTION_PERMISSION_MAP = {"update": "write", "list": "read", "report": "report", "export": "export"}


def _user(user=None):
    return user or frappe.session.user


def check_doctype_permission(doctype, action, user=None):
    """Check a supported DocType action through Frappe's role permission engine."""
    user = _user(user)
    permission_type = ACTION_PERMISSION_MAP.get(action, action)
    if permission_type == "cancel":
        permission_type = "cancel"
    return bool(frappe.has_permission(doctype=doctype, ptype=permission_type, user=user))


def check_record_permission(doctype, name, action, user=None):
    user = _user(user)
    doc = frappe.get_doc(doctype, name)
    permission_type = ACTION_PERMISSION_MAP.get(action, action)
    return bool(doc.has_permission(permission_type, user=user))


def get_risk_level(action, doctype=None):
    key = str(action or "read").lower()
    doctype_key = str(doctype or "").lower().replace(" ", "_")
    if key in HIGH_RISK_ACTIONS or "payment_entry" in doctype_key or "journal_entry" in doctype_key:
        return "high"
    if key in MEDIUM_RISK_ACTIONS:
        return "medium"
    return "low" if key in LOW_RISK_ACTIONS else "medium"


def is_confirmation_required(action, doctype=None):
    return get_risk_level(action, doctype) == "high"


def guard_action(doctype=None, name=None, action="read", fields=None, payload=None, user=None):
    user = _user(user)
    risk_level = get_risk_level(action, doctype)
    result = {"allowed": False, "reason": None, "filtered_fields": [], "blocked_fields": [], "risk_level": risk_level, "confirmation_required": is_confirmation_required(action, doctype), "audit_required": True}
    if user == "Guest":
        result["reason"] = "Guest users cannot access ERP data."
        return result
    if doctype and doctype in BLOCKED_DOCTYPES_BY_DEFAULT and "System Manager" not in frappe.get_roles(user):
        result["reason"] = f"{doctype} is blocked from AI access by default."
        return result
    if doctype and not check_doctype_permission(doctype, action, user):
        result["reason"] = f"You do not have permission to {action} {doctype}."
        return result
    if doctype and name and not check_record_permission(doctype, name, action, user):
        result["reason"] = f"You do not have permission to {action} this {doctype} record."
        return result
    requested = frappe.parse_json(fields) if isinstance(fields, str) else (fields or list((payload or {}).keys()))
    if doctype:
        allowed_fields = get_allowed_fields(doctype, requested, user)
        result["filtered_fields"] = allowed_fields
        result["blocked_fields"] = [field for field in requested if field not in allowed_fields]
    result["allowed"] = True
    return result
