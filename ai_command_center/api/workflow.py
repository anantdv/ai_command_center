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
    """Return Workflow Action documents assigned to the current user.

    This endpoint intentionally uses Frappe's Workflow Action and document
    permission APIs. It does not inspect tables directly and does not bypass
    permissions.
    """

    if frappe.session.user == "Guest":
        frappe.throw("Login required.", frappe.AuthenticationError)

    limit = max(1, min(int(limit or 50), 100))
    filters = {"user": frappe.session.user, "status": "Open"}
    if doctype:
        filters["reference_doctype"] = doctype

    actions = frappe.db.get_list(
        "Workflow Action",
        filters=filters,
        fields=["name", "reference_doctype", "reference_name", "workflow_state", "creation"],
        order_by="creation desc",
        limit_page_length=limit,
    )

    documents = []
    for action in actions:
        doc = _safe_get_document(action.reference_doctype, action.reference_name)
        if not doc:
            continue
        documents.append(_pending_document_payload(doc, action))

    log_ai_action(
        frappe.session.user,
        "workflow_pending_approvals_viewed",
        doctype,
        None,
        True,
        {"count": len(documents)},
    )
    return success({"documents": documents, "total": len(documents), "filters": {"doctype": doctype} if doctype else {}})


@frappe.whitelist()
@safe_api
def get_workflow_document_detail(doctype, name):
    doc = _safe_get_document(doctype, name, throw=True)
    payload = _document_detail_payload(doc)
    log_ai_action(frappe.session.user, "workflow_document_detail_viewed", doctype, name, True, {})
    return success(payload)


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
    log_ai_action(frappe.session.user, "workflow_action_applied", doctype, name, True, {"action": action})
    return success({
        "doctype": doctype,
        "name": name,
        "action": action,
        "previous_state": previous_state,
        "new_state": getattr(updated, "workflow_state", None),
        "status": getattr(updated, "status", None),
        "message": f'ERPNext workflow action "{action}" applied.',
        "result": {"name": updated.name},
    })


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


def _pending_document_payload(doc, action):
    summary = _summary(doc)
    return {
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
        "available_actions": _available_workflow_actions(doc),
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


def _document_title(doc):
    title_field = doc.meta.title_field
    if title_field and doc.get(title_field):
        return str(doc.get(title_field))
    return str(doc.name)
