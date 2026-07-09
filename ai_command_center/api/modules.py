import frappe

from ai_command_center.utils.response import safe_api, success


MODULE_REGISTRY = {
    "Selling": {"label": "Selling", "route": "/modules/selling", "doctypes": ["Customer", "Lead", "Opportunity", "Quotation", "Sales Order", "Sales Invoice", "Delivery Note", "Item"]},
    "Buying": {"label": "Buying", "route": "/modules/buying", "doctypes": ["Supplier", "Request for Quotation", "Supplier Quotation", "Purchase Order", "Purchase Invoice", "Purchase Receipt", "Material Request", "Item"]},
    "Stock": {"label": "Stock", "route": "/modules/stock", "doctypes": ["Item", "Warehouse", "Stock Entry", "Stock Reconciliation", "Delivery Note", "Purchase Receipt"]},
    "Accounts": {"label": "Accounts", "route": "/modules/accounts", "doctypes": ["Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry", "GL Entry", "Account"]},
    "CRM": {"label": "CRM", "route": "/modules/crm", "doctypes": ["Lead", "Opportunity", "Customer", "Contact"]},
    "Projects": {"label": "Projects", "route": "/modules/projects", "doctypes": ["Project", "Task", "Timesheet"]},
    "HR": {"label": "HR", "route": "/modules/hr", "doctypes": ["Employee", "Leave Application", "Attendance"]},
    "Manufacturing": {"label": "Manufacturing", "route": "/modules/manufacturing", "doctypes": ["Work Order", "BOM", "Production Plan", "Job Card"]},
}


@frappe.whitelist()
@safe_api
def get_accessible_modules():
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Authentication required.", frappe.AuthenticationError)
    modules = []
    for module_name, config in MODULE_REGISTRY.items():
        doctypes = _permitted_doctypes(config["doctypes"], user)
        if doctypes:
            modules.append({"module_name": module_name, "label": config["label"], "route": config["route"], "accessible": True, "doctypes": doctypes})
    return success({"modules": modules})


@frappe.whitelist()
@safe_api
def get_module_permissions(module_name):
    config = MODULE_REGISTRY.get(_normalize(module_name))
    if not config:
        frappe.throw("Module is not registered.", frappe.ValidationError)
    doctypes = _permitted_doctypes(config["doctypes"], frappe.session.user)
    return success({"module_name": _normalize(module_name), "accessible": bool(doctypes), "doctypes": doctypes})


@frappe.whitelist()
@safe_api
def get_doctype_read_permissions(doctypes):
    doctypes = frappe.parse_json(doctypes) if isinstance(doctypes, str) else (doctypes or [])
    return success({"doctypes": _permitted_doctypes(doctypes, frappe.session.user)})


def _permitted_doctypes(doctypes, user):
    output = []
    for doctype in doctypes:
        if frappe.db.exists("DocType", doctype) and frappe.has_permission(doctype=doctype, ptype="read", user=user):
            output.append(doctype)
    return output


def _normalize(value):
    text = str(value or "").strip().replace("-", " ").replace("_", " ").lower()
    aliases = {"accounting": "Accounts", "accounts": "Accounts", "selling": "Selling", "buying": "Buying", "stock": "Stock", "crm": "CRM", "projects": "Projects", "hr": "HR", "manufacturing": "Manufacturing"}
    return aliases.get(text, " ".join(part.capitalize() for part in text.split()))
