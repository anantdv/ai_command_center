import frappe
from frappe.utils import now_datetime

from ai_command_center.utils.permission_guard import get_risk_level
from ai_command_center.utils.response import safe_api, success


def log_ai_action(user, action, doctype=None, record_name=None, allowed=True, details=None):
    details = details or {}
    doc = frappe.new_doc("AI Permission Audit")
    doc.update({
        "user": user or frappe.session.user,
        "action": action,
        "doctype_name": doctype,
        "record_name": record_name,
        "allowed": int(bool(allowed)),
        "reason": details.get("reason"),
        "risk_level": details.get("risk_level") or get_risk_level(action, doctype),
        "agent_name": details.get("agent_name"),
        "tool_name": details.get("tool_name"),
        "input_summary": details.get("input_summary"),
        "output_summary": details.get("output_summary"),
        "ip_address": getattr(frappe.local, "request_ip", None),
        "created_at": now_datetime(),
    })
    doc.insert()
    return doc.name


@frappe.whitelist()
@safe_api
def create_audit_log(event):
    roles = set(frappe.get_roles(frappe.session.user))
    if not roles.intersection({"System Manager", "AI Command Center Manager"}):
        frappe.throw(
            "Only an AI Command Center Manager can register external audit events.",
            frappe.PermissionError,
        )
    event = frappe.parse_json(event) if isinstance(event, str) else (event or {})
    action = event.get("action")
    if not action:
        frappe.throw("Action is required.", frappe.ValidationError)
    name = log_ai_action(frappe.session.user, action, event.get("doctype"), event.get("record_name"), event.get("allowed", True), event)
    return success({"name": name})
