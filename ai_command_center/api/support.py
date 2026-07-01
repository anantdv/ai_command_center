import frappe

from ai_command_center.utils.response import safe_api, success


@frappe.whitelist()
@safe_api
def create_support_ticket(subject, description, priority="Medium", category=None, conversation_id=None):
    if frappe.db.exists("DocType", "Issue") and frappe.has_permission("Issue", "create"):
        doc = frappe.new_doc("Issue")
        doc.subject = subject
        doc.description = description
        if doc.meta.has_field("priority"):
            doc.priority = priority
        if doc.meta.has_field("raised_by"):
            doc.raised_by = frappe.session.user
    else:
        if not frappe.has_permission("AI Support Interaction", "create"):
            frappe.throw("You do not have permission to create a support interaction.", frappe.PermissionError)
        doc = frappe.new_doc("AI Support Interaction")
        doc.update({"subject": subject, "description": description, "priority": priority, "status": "Open", "category": category, "conversation": conversation_id, "created_by_user": frappe.session.user})
    doc.insert()
    return success({"name": doc.name, "doctype": doc.doctype, "status": doc.get("status") or "Open"}, "Support ticket created")


@frappe.whitelist()
@safe_api
def list_support_tickets(status=None):
    doctype = "Issue" if frappe.db.exists("DocType", "Issue") and frappe.has_permission("Issue", "read") else "AI Support Interaction"
    filters = {"status": status} if status else {}
    fields = ["name", "subject", "status", "priority", "creation"]
    return success(frappe.db.get_list(doctype, filters=filters, fields=fields, order_by="creation desc", limit_page_length=200))
