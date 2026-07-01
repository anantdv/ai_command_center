import frappe

ROLES = ["AI Command Center Manager", "AI Command Center User", "AI Training Manager", "AI Support Agent"]


def _ensure_roles():
    for role_name in ROLES:
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1}).insert()


def before_install():
    """Ensure permission rows can resolve their custom roles during DocType sync."""
    _ensure_roles()


def after_install():
    """Idempotently verify app roles without assigning them to users."""
    _ensure_roles()
