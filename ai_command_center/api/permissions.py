import frappe

from ai_command_center.utils.permission_guard import guard_action
from ai_command_center.utils.response import safe_api, success


@frappe.whitelist()
@safe_api
def check_permission(action, doctype=None, record_name=None, fields=None, payload=None):
    payload = frappe.parse_json(payload) if isinstance(payload, str) else payload
    return success(guard_action(doctype, record_name, action, fields, payload))


@frappe.whitelist()
@safe_api
def explain_permission_denial(action, doctype=None, record_name=None):
    result = guard_action(doctype, record_name, action)
    if result["allowed"]:
        explanation = f"You are allowed to {action} {doctype or 'this resource'}."
    else:
        explanation = result["reason"] or "This action is restricted by your ERPNext permissions."
    return success({"allowed": result["allowed"], "explanation": explanation, "risk_level": result["risk_level"]})
