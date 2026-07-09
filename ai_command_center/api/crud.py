import hmac

import frappe

from ai_command_center.api.audit import log_ai_action
from ai_command_center.utils.field_filter import filter_output_fields, get_allowed_fields, get_writable_fields
from ai_command_center.utils.permission_guard import guard_action
from ai_command_center.utils.query_sanitizer import sanitize_fields, sanitize_filters, sanitize_limit, sanitize_order_by
from ai_command_center.utils.response import error, safe_api, success


def _guard_or_error(doctype, action, name=None, fields=None, payload=None):
    result = guard_action(doctype, name, action, fields, payload)
    log_ai_action(frappe.session.user, action, doctype, name, result["allowed"], result)
    return result


@frappe.whitelist()
@safe_api
def list_records(doctype, filters=None, fields=None, limit=20, order_by=None):
    requested = sanitize_fields(doctype, fields)
    guard = _guard_or_error(doctype, "list", fields=requested)
    if not guard["allowed"]:
        return error(guard["reason"], {"doctype": doctype, "action": "list"})
    allowed = get_allowed_fields(doctype, requested)
    rows = frappe.db.get_list(
        doctype,
        filters=sanitize_filters(doctype, filters),
        fields=allowed,
        order_by=sanitize_order_by(doctype, order_by),
        limit_page_length=sanitize_limit(limit),
    )
    return success({"records": filter_output_fields(doctype, rows, allowed), "fields": allowed, "count": len(rows), "permission": guard})


@frappe.whitelist()
@safe_api
def get_record(doctype, name, fields=None):
    requested = sanitize_fields(doctype, fields)
    guard = _guard_or_error(doctype, "read", name, requested)
    if not guard["allowed"]:
        return error(guard["reason"], {"doctype": doctype, "name": name})
    doc = frappe.get_doc(doctype, name)
    if not doc.has_permission("read"):
        frappe.throw("Record permission denied.", frappe.PermissionError)
    allowed = get_allowed_fields(doctype, requested)
    output = filter_output_fields(doctype, doc.as_dict(), allowed)
    # docstatus is a standard document property rather than a normal meta field.
    # Return it only when explicitly requested so draft-only policies can be
    # revalidated immediately before a controlled write.
    if "docstatus" in requested:
        output["docstatus"] = int(doc.docstatus or 0)
    return success({"record": output, "permission": guard})


@frappe.whitelist()
@safe_api
def get_document_detail(doctype, name):
    guard = _guard_or_error(doctype, "read", name)
    if not guard["allowed"]:
        return error(guard["reason"], {"doctype": doctype, "name": name})
    doc = frappe.get_doc(doctype, name)
    if not doc.has_permission("read"):
        frappe.throw("Record permission denied.", frappe.PermissionError)
    allowed = get_allowed_fields(doctype)
    fields = filter_output_fields(doctype, doc.as_dict(), allowed)
    summary = _build_document_summary(doc, fields)
    return success({
        "doctype": doctype,
        "name": doc.name,
        "title": _document_title(doc),
        "docstatus": int(doc.docstatus or 0),
        "status": fields.get("status") or getattr(doc, "status", None),
        "workflow_state": fields.get("workflow_state") or getattr(doc, "workflow_state", None),
        "summary": summary,
        "fields": fields,
        "items": _safe_child_items(doc),
        "available_workflow_actions": _available_workflow_actions(doc),
        "permission": guard,
    })


@frappe.whitelist()
@safe_api
def create_record(doctype, data):
    data = frappe.parse_json(data) if isinstance(data, str) else (data or {})
    guard = _guard_or_error(doctype, "create", payload=data)
    if not guard["allowed"]:
        return error(guard["reason"], {"doctype": doctype, "action": "create"})
    if data.get("docstatus") not in (None, 0, "0"):
        return error("AI-created records must remain Draft.")
    allowed = get_writable_fields(doctype, data.keys())
    blocked = [field for field in data if field not in allowed]
    doc = frappe.new_doc(doctype)
    for field in allowed:
        doc.set(field, data[field])
    doc.docstatus = 0
    doc.insert()
    return success({"name": doc.name, "docstatus": doc.docstatus, "status": "Draft", "blocked_fields": blocked, "permission": guard}, "Draft created")


@frappe.whitelist()
@safe_api
def update_record(doctype, name, data):
    data = frappe.parse_json(data) if isinstance(data, str) else (data or {})
    guard = _guard_or_error(doctype, "update", name, payload=data)
    if not guard["allowed"]:
        return error(guard["reason"], {"doctype": doctype, "name": name})
    doc = frappe.get_doc(doctype, name)
    if not doc.has_permission("write"):
        frappe.throw("Record write permission denied.", frappe.PermissionError)
    if doctype == "Quotation" and int(doc.docstatus or 0) != 0:
        return error("Only Draft Quotations can be updated through AI Command Center.", {"doctype": doctype, "name": name})
    allowed = get_writable_fields(doctype, data.keys())
    blocked = [field for field in data if field not in allowed]
    for field in allowed:
        doc.set(field, data[field])
    doc.save()
    return success({"name": doc.name, "docstatus": doc.docstatus, "blocked_fields": blocked, "permission": guard}, "Record updated")


@frappe.whitelist()
@safe_api
def delete_record(doctype, name, confirmation_token=None):
    guard = _guard_or_error(doctype, "delete", name)
    if not guard["allowed"]:
        return error(guard["reason"], {"doctype": doctype, "name": name})
    expected = frappe.cache().get_value(f"ai_cc_confirmation:{frappe.session.user}:{doctype}:{name}:delete")
    supplied = str(confirmation_token or "")
    expected = expected.decode() if isinstance(expected, bytes) else str(expected or "")
    if not expected or not hmac.compare_digest(supplied, expected):
        return success({"confirmation_required": True, "risk_level": "high", "action": "delete", "doctype": doctype, "name": name}, "Explicit confirmation is required")
    frappe.delete_doc(doctype, name)
    frappe.cache().delete_value(f"ai_cc_confirmation:{frappe.session.user}:{doctype}:{name}:delete")
    return success({"deleted": True, "name": name})


def _document_title(doc):
    title_field = frappe.get_meta(doc.doctype).title_field
    if title_field and doc.get(title_field):
        return str(doc.get(title_field))
    return str(doc.name)


def _build_document_summary(doc, fields):
    keys = (
        "customer", "supplier", "party_name", "customer_name", "supplier_name", "item_name",
        "posting_date", "transaction_date", "grand_total", "outstanding_amount", "currency",
        "workflow_state", "status",
    )
    return {key: fields.get(key) for key in keys if fields.get(key) not in (None, "")}


def _safe_child_items(doc):
    if not hasattr(doc, "items") or not doc.items:
        return []
    allowed = {
        "name", "item_code", "item_name", "description", "qty", "uom", "stock_uom",
        "rate", "amount", "warehouse", "schedule_date", "delivery_date",
    }
    return [{key: row.get(key) for key in allowed if row.get(key) not in (None, "")} for row in doc.items]


def _available_workflow_actions(doc):
    try:
        from frappe.model.workflow import get_transitions

        transitions = get_transitions(doc) or []
        return [
            {
                "action": transition.get("action"),
                "next_state": transition.get("next_state"),
                "allowed": True,
            }
            for transition in transitions
            if transition.get("action")
        ]
    except Exception:
        return []
