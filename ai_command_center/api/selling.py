import frappe

from ai_command_center.utils.response import safe_api, success


@frappe.whitelist()
@safe_api
def get_selling_summary():
    """Lightweight optional Selling summary for future optimized dashboards."""

    summary = {}
    for doctype in ("Customer", "Quotation", "Sales Order", "Sales Invoice"):
        if frappe.has_permission(doctype=doctype, ptype="read", user=frappe.session.user):
            rows = frappe.db.get_list(doctype, fields=["name"], limit_page_length=500)
            summary[doctype] = len(rows)
    return success(summary)


@frappe.whitelist()
@safe_api
def get_recent_selling_documents(limit=10):
    limit = max(1, min(int(limit or 10), 50))
    output = []
    for doctype in ("Customer", "Quotation", "Sales Order", "Sales Invoice"):
        if not frappe.has_permission(doctype=doctype, ptype="read", user=frappe.session.user):
            continue
        rows = frappe.db.get_list(doctype, fields=["name", "modified"], order_by="modified desc", limit_page_length=limit)
        output.extend({"doctype": doctype, "name": row.name, "modified": str(row.modified or "")} for row in rows)
    return success(sorted(output, key=lambda row: row.get("modified") or "", reverse=True)[:limit])
