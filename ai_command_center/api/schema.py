import frappe

from ai_command_center.utils.constants import BLOCKED_DOCTYPES_BY_DEFAULT
from ai_command_center.utils.field_filter import get_allowed_fields
from ai_command_center.utils.permission_guard import check_doctype_permission
from ai_command_center.utils.response import safe_api, success


@frappe.whitelist()
@safe_api
def get_allowed_doctypes(module=None):
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Authentication required.", frappe.AuthenticationError)
    filters = {"istable": 0, "issingle": 0}
    if module:
        filters["module"] = module
    rows = frappe.db.get_list("DocType", filters=filters, fields=["name", "module"], order_by="module asc, name asc", limit_page_length=500)
    is_manager = "System Manager" in frappe.get_roles(user)
    allowed = []
    for row in rows:
        if row.name in BLOCKED_DOCTYPES_BY_DEFAULT and not is_manager:
            continue
        if check_doctype_permission(row.name, "read", user):
            allowed.append({"name": row.name, "label": row.name, "module": row.module})
    return success(allowed)


@frappe.whitelist()
@safe_api
def get_allowed_modules():
    response = get_allowed_doctypes()
    if not response.get("success"):
        return response
    return success(sorted({row["module"] for row in response["data"] if row.get("module")}))


@frappe.whitelist()
@safe_api
def get_doctype_schema(doctype):
    if not check_doctype_permission(doctype, "read"):
        frappe.throw(f"You do not have permission to read {doctype}.", frappe.PermissionError)
    meta = frappe.get_meta(doctype)
    allowed = set(get_allowed_fields(doctype))
    fields = []
    for field in meta.fields:
        if field.fieldname not in allowed:
            continue
        fields.append({key: field.get(key) for key in ("fieldname", "label", "fieldtype", "options", "reqd", "read_only", "hidden", "permlevel")})
    return success({
        "doctype": doctype,
        "module": meta.module,
        "is_submittable": bool(meta.is_submittable),
        "fields": fields,
        "permissions": {
            "can_read": check_doctype_permission(doctype, "read"),
            "can_create": check_doctype_permission(doctype, "create"),
            "can_write": check_doctype_permission(doctype, "write"),
            "can_delete": check_doctype_permission(doctype, "delete"),
            "can_submit": bool(meta.is_submittable and check_doctype_permission(doctype, "submit")),
            "can_cancel": bool(meta.is_submittable and check_doctype_permission(doctype, "cancel")),
            "can_export": check_doctype_permission(doctype, "export"),
        },
    })
