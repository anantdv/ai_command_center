import time

import frappe

from ai_command_center.api.audit import log_ai_action
from ai_command_center.utils.response import error, safe_api, success


SUMMARY_FIELDS = (
    "customer",
    "supplier",
    "party_name",
    "customer_name",
    "supplier_name",
    "posting_date",
    "transaction_date",
    "grand_total",
    "outstanding_amount",
    "currency",
    "status",
    "workflow_state",
)

ITEM_FIELDS = {
    "name",
    "item_code",
    "item_name",
    "description",
    "qty",
    "uom",
    "stock_uom",
    "rate",
    "amount",
    "warehouse",
    "schedule_date",
    "delivery_date",
}


@frappe.whitelist()
@safe_api
def get_pending_workflow_documents(doctype=None, limit=50):
    """Return Workflow Action documents currently actionable by this session.

    ERPNext Desk does not show pending workflow approvals by filtering only
    ``Workflow Action.user``. Modern Frappe creates role-based Workflow Action
    rows with child ``permitted_roles`` and uses the Workflow Action DocType's
    permission query conditions. Therefore this method queries open Workflow
    Action rows through ``frappe.db.get_list`` and lets Frappe apply those
    native permission conditions, then revalidates document read permission and
    current transitions.
    """

    started = time.time()
    if frappe.session.user == "Guest":
        frappe.throw("Login required.", frappe.AuthenticationError)

    limit = max(1, min(int(limit or 50), 100))
    filters = {"status": "Open"}
    if doctype:
        filters["reference_doctype"] = doctype

    fields = _workflow_action_fields()
    actions = frappe.db.get_list(
        "Workflow Action",
        filters=filters,
        fields=fields,
        order_by="modified desc",
        limit_page_length=limit,
    )

    documents = []
    permission_filtered = 0
    transition_filtered = 0
    for action in actions:
        doc = _safe_get_document(action.reference_doctype, action.reference_name)
        if not doc:
            permission_filtered += 1
            continue
        available_actions = _available_workflow_actions(doc)
        if not available_actions:
            transition_filtered += 1
            continue
        documents.append(_pending_document_payload(doc, action, available_actions))

    log_ai_action(
        frappe.session.user,
        "workflow_pending_approvals_viewed",
        doctype,
        None,
        True,
        {
            "workflow_actions_found": len(actions),
            "after_permission_filter": len(actions) - permission_filtered,
            "after_transition_filter": len(documents),
            "returned": len(documents),
            "duration_ms": int((time.time() - started) * 1000),
        },
    )
    return success({"documents": documents, "total": len(documents), "filters": {"doctype": doctype} if doctype else {}})


@frappe.whitelist()
@safe_api
def get_pending(doctype=None, limit=50):
    return get_pending_workflow_documents(doctype=doctype, limit=limit)


@frappe.whitelist()
@safe_api
def get_pending_by_doctype(doctype, limit=50):
    return get_pending_workflow_documents(doctype=doctype, limit=limit)


@frappe.whitelist()
@safe_api
def get_workflow_document_detail(doctype, name):
    doc = _safe_get_document(doctype, name, throw=True)
    payload = _document_detail_payload(doc)
    log_ai_action(frappe.session.user, "workflow_document_detail_viewed", doctype, name, True, {})
    return success(payload)


@frappe.whitelist()
@safe_api
def get_document(doctype, name):
    return get_workflow_document_detail(doctype, name)


@frappe.whitelist()
@safe_api
def get_available_workflow_actions(doctype, name):
    doc = _safe_get_document(doctype, name, throw=True)
    actions = _available_workflow_actions(doc)
    log_ai_action(frappe.session.user, "workflow_actions_loaded", doctype, name, True, {"count": len(actions)})
    return success({"actions": actions, "doctype": doctype, "name": name})


@frappe.whitelist()
@safe_api
def apply_workflow_action(doctype, name, action, comment=None, confirmation_id=None):
    """Apply a workflow action through Frappe's standard workflow engine.

    FastAPI shows a confirmation card before calling this method. This method
    still revalidates that the transition is available to the current user.
    """

    del confirmation_id
    doc = _safe_get_document(doctype, name, throw=True)
    available = {item["action"] for item in _available_workflow_actions(doc)}
    if action not in available:
        frappe.throw("This workflow action is not available for your user on this document.", frappe.PermissionError)

    previous_state = getattr(doc, "workflow_state", None)
    from frappe.model.workflow import apply_workflow

    if comment:
        doc.add_comment("Comment", text=comment)
    updated = apply_workflow(doc, action)
    available_actions = _available_workflow_actions(updated)
    log_ai_action(frappe.session.user, "workflow_action_applied", doctype, name, True, {"action": action})
    return success({
        "doctype": doctype,
        "name": name,
        "action": action,
        "previous_state": previous_state,
        "new_state": getattr(updated, "workflow_state", None),
        "status": getattr(updated, "status", None),
        "available_actions": available_actions,
        "message": f'ERPNext workflow action "{action}" applied.',
        "result": {"name": updated.name},
    })


@frappe.whitelist()
@safe_api
def action(doctype, name, action, comment=None, confirmation_id=None):
    return apply_workflow_action(doctype=doctype, name=name, action=action, comment=comment, confirmation_id=confirmation_id)


@frappe.whitelist()
@safe_api
def debug(doctype=None, limit=50):
    """Temporary workflow diagnostics. Enable only in developer/debug mode."""

    if not _debug_enabled():
        frappe.throw("Workflow debug endpoint is disabled.", frappe.PermissionError)
    if frappe.session.user == "Guest":
        frappe.throw("Login required.", frappe.AuthenticationError)

    limit = max(1, min(int(limit or 50), 100))
    filters = {"status": "Open"}
    if doctype:
        filters["reference_doctype"] = doctype
    actions = frappe.db.get_list(
        "Workflow Action",
        filters=filters,
        fields=_workflow_action_fields(),
        order_by="modified desc",
        limit_page_length=limit,
    )
    records = []
    permission_filtered = 0
    transition_filtered = 0
    for action_doc in actions:
        doc = _safe_get_document(action_doc.reference_doctype, action_doc.reference_name)
        if not doc:
            permission_filtered += 1
            records.append(_workflow_action_debug_row(action_doc, "permission_filtered", []))
            continue
        transitions = _available_workflow_actions(doc)
        if not transitions:
            transition_filtered += 1
            records.append(_workflow_action_debug_row(action_doc, "transition_filtered", []))
            continue
        records.append(_workflow_action_debug_row(action_doc, "returned", transitions))

    payload = {
        "session_user": frappe.session.user,
        "site": getattr(frappe.local, "site", None),
        "roles": frappe.get_roles(frappe.session.user),
        "incoming_cookie_names": sorted(list(getattr(getattr(frappe, "request", None), "cookies", {}) or {})),
        "workflow_actions_found": len(actions),
        "after_permission_filter": len(actions) - permission_filtered,
        "after_transition_filter": len(actions) - permission_filtered - transition_filtered,
        "records": records,
    }
    return success(payload)


def _safe_get_document(doctype, name, throw=False):
    if not doctype or not name:
        if throw:
            frappe.throw("DocType and document name are required.", frappe.ValidationError)
        return None
    if not frappe.has_permission(doctype=doctype, ptype="read", doc=name, user=frappe.session.user):
        if throw:
            frappe.throw(f"You do not have permission to read {doctype} {name}.", frappe.PermissionError)
        return None
    try:
        doc = frappe.get_doc(doctype, name)
    except frappe.DoesNotExistError:
        if throw:
            raise
        return None
    if not doc.has_permission("read"):
        if throw:
            frappe.throw(f"You do not have permission to read {doctype} {name}.", frappe.PermissionError)
        return None
    return doc


def _pending_document_payload(doc, action, available_actions=None):
    summary = _summary(doc)
    return {
        "workflow_action_name": action.name,
        "doctype": doc.doctype,
        "name": doc.name,
        "title": _document_title(doc),
        "workflow_state": summary.get("workflow_state") or getattr(doc, "workflow_state", None) or action.workflow_state,
        "status": summary.get("status") or getattr(doc, "status", None),
        "owner": getattr(doc, "owner", None),
        "modified": str(getattr(doc, "modified", "") or ""),
        "posting_date": str(summary.get("posting_date") or "") or None,
        "transaction_date": str(summary.get("transaction_date") or "") or None,
        "party": summary.get("customer") or summary.get("supplier") or summary.get("party_name"),
        "grand_total": summary.get("grand_total"),
        "currency": summary.get("currency"),
        "available_actions": available_actions or _available_workflow_actions(doc),
    }


def _document_detail_payload(doc):
    fields = _safe_fields(doc)
    return {
        "doctype": doc.doctype,
        "name": doc.name,
        "title": _document_title(doc),
        "workflow_state": fields.get("workflow_state") or getattr(doc, "workflow_state", None),
        "status": fields.get("status") or getattr(doc, "status", None),
        "docstatus": int(doc.docstatus or 0),
        "summary": _summary(doc, fields),
        "fields": fields,
        "items": _safe_child_items(doc),
        "available_actions": _available_workflow_actions(doc),
        "permission": {"allowed": True, "risk_level": "low", "confirmation_required": False},
    }


def _safe_fields(doc):
    blocked_keywords = ("password", "secret", "token", "api_key", "api_secret", "otp", "salary", "bank", "account_no", "pan", "aadhaar")
    output = {"name": doc.name}
    for field in doc.meta.fields:
        fieldname = field.fieldname
        if not fieldname or field.fieldtype in {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Table"}:
            continue
        label = field.label or ""
        if any(keyword in f"{fieldname} {label}".lower() for keyword in blocked_keywords):
            continue
        if field.hidden:
            continue
        output[fieldname] = doc.get(fieldname)
    output["docstatus"] = int(doc.docstatus or 0)
    return output


def _summary(doc, fields=None):
    fields = fields or _safe_fields(doc)
    return {key: fields.get(key) for key in SUMMARY_FIELDS if fields.get(key) not in (None, "")}


def _safe_child_items(doc):
    if not hasattr(doc, "items") or not doc.items:
        return []
    return [{key: row.get(key) for key in ITEM_FIELDS if row.get(key) not in (None, "")} for row in doc.items]


def _available_workflow_actions(doc):
    try:
        from frappe.model.workflow import get_transitions

        transitions = get_transitions(doc) or []
        return [
            {"action": transition.get("action"), "next_state": transition.get("next_state"), "allowed": True}
            for transition in transitions
            if transition.get("action")
        ]
    except Exception:
        return []


def _workflow_action_fields():
    fields = ["name", "reference_doctype", "reference_name", "workflow_state", "status", "creation", "modified"]
    if frappe.db.has_column("Workflow Action", "user"):
        fields.append("user")
    return fields


def _debug_enabled():
    return bool(
        frappe.conf.get("developer_mode")
        or frappe.conf.get("debug")
        or frappe.conf.get("DEBUG")
        or frappe.conf.get("enable_ai_command_center_debug")
    )


def _workflow_action_debug_row(action_doc, diagnostic_status, transitions):
    return {
        "workflow_action_name": action_doc.name,
        "reference_doctype": action_doc.reference_doctype,
        "reference_name": action_doc.reference_name,
        "workflow_state": action_doc.workflow_state,
        "status": action_doc.status,
        "user": action_doc.get("user"),
        "creation": str(action_doc.creation or ""),
        "modified": str(action_doc.modified or ""),
        "diagnostic_status": diagnostic_status,
        "available_actions": transitions,
    }


def _document_title(doc):
    title_field = doc.meta.title_field
    if title_field and doc.get(title_field):
        return str(doc.get(title_field))
    return str(doc.name)
