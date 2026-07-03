import frappe

from ai_command_center.utils.response import safe_api, success


@frappe.whitelist()
@safe_api
def get_current_user_context():
    user = frappe.session.user
    if user == "Guest":
        frappe.throw("Authentication required.", frappe.AuthenticationError)
    roles = frappe.get_roles(user)
    company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
    company_currency = frappe.db.get_value("Company", company, "default_currency") if company else None
    company_currency = company_currency or frappe.db.get_single_value("Global Defaults", "default_currency") or "INR"
    permissions = frappe.permissions.get_user_permissions(user) or {}
    allowed_companies = [item.get("doc") for item in permissions.get("Company", []) if item.get("doc")]
    if company and company not in allowed_companies:
        allowed_companies.insert(0, company)
    user_doc = frappe.get_cached_doc("User", user)
    return success({
        "user": user,
        "full_name": user_doc.full_name or user,
        "roles": roles,
        "company": company,
        "company_currency": company_currency,
        "allowed_companies": allowed_companies,
        "timezone": user_doc.time_zone or frappe.db.get_single_value("System Settings", "time_zone"),
        "language": user_doc.language or frappe.local.lang or "en",
        "is_guest": False,
    })
