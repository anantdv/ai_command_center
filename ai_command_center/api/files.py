import frappe
from frappe.utils import getdate, nowdate

from ai_command_center.utils.permission_guard import guard_action
from ai_command_center.utils.response import error, safe_api, success


def _normalise_roles(value):
    value = frappe.parse_json(value) if isinstance(value, str) else value
    if not value:
        return []
    if not isinstance(value, (list, tuple)):
        frappe.throw("allowed_roles must be a JSON array.", frappe.ValidationError)
    return [str(role) for role in value if role]


def _can_read_file_url(file_url):
    file_name = frappe.db.get_value("File", {"file_url": file_url}, "name") if file_url else None
    if not file_name:
        return True
    return bool(frappe.get_doc("File", file_name).has_permission("read"))


@frappe.whitelist()
@safe_api
def register_generated_file(file_url, file_name, file_type, source_doctype=None, source_report=None, metadata=None):
    guard = guard_action("AI Generated File", action="create")
    if not guard["allowed"]:
        return error(guard["reason"])
    if file_url and frappe.db.exists("File", {"file_url": file_url}):
        file_doc = frappe.get_doc("File", frappe.db.get_value("File", {"file_url": file_url}, "name"))
        if not file_doc.has_permission("read"):
            frappe.throw("You cannot register a file you cannot read.", frappe.PermissionError)
    metadata = frappe.parse_json(metadata) if isinstance(metadata, str) else (metadata or {})
    allowed_roles = _normalise_roles(metadata.get("allowed_roles"))
    doc = frappe.new_doc("AI Generated File")
    doc.update({
        "file_title": file_name,
        "file_type": file_type,
        "file_url": file_url,
        "generated_by": frappe.session.user,
        "source_conversation": metadata.get("source_conversation"),
        "source_doctype": source_doctype,
        "source_report": source_report,
        "filters_json": frappe.as_json(metadata.get("filters") or {}),
        "access_policy": metadata.get("access_policy") or "Private",
        "allowed_roles": frappe.as_json(allowed_roles),
        "expiry_date": metadata.get("expiry_date"),
    })
    doc.insert()
    return success({"name": doc.name})


@frappe.whitelist()
@safe_api
def list_generated_files(file_type=None):
    filters = {"file_type": file_type} if file_type else {}
    fields = ["name", "owner", "file_title", "file_type", "file_url", "generated_by", "source_doctype", "source_report", "access_policy", "allowed_roles", "expiry_date"]
    rows = frappe.db.get_list("AI Generated File", filters=filters, fields=fields, order_by="creation desc", limit_page_length=200)
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    is_manager = bool(roles.intersection({"System Manager", "AI Command Center Manager"}))
    visible = []
    for row in rows:
        if row.expiry_date and getdate(row.expiry_date) < getdate(nowdate()):
            continue
        policy_roles = set(_normalise_roles(row.allowed_roles))
        owns_file = row.owner == user or row.generated_by == user
        policy_allows = row.access_policy == "Role Based" and bool(roles.intersection(policy_roles))
        if not (is_manager or owns_file or policy_allows):
            continue
        if not _can_read_file_url(row.file_url):
            continue
        item = dict(row)
        item.pop("owner", None)
        item.pop("allowed_roles", None)
        visible.append(item)
    return success(visible)
