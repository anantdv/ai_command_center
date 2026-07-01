import frappe

from ai_command_center.utils.constants import SENSITIVE_FIELD_KEYWORDS, TECHNICAL_FIELDS


def _is_sensitive(fieldname, label=None):
    text = f"{fieldname or ''} {label or ''}".lower()
    return any(keyword in text for keyword in SENSITIVE_FIELD_KEYWORDS)


def _can_read_permlevel(meta, permlevel, user):
    if int(permlevel or 0) == 0:
        return True
    roles = set(frappe.get_roles(user))
    return any(
        permission.role in roles
        and int(permission.permlevel or 0) == int(permlevel)
        and bool(permission.read)
        for permission in meta.permissions
    )


def get_allowed_fields(doctype, requested_fields=None, user=None):
    """Return a conservative field allowlist for the current user's readable permlevels."""
    user = user or frappe.session.user
    meta = frappe.get_meta(doctype)
    requested = frappe.parse_json(requested_fields) if isinstance(requested_fields, str) else requested_fields
    requested_set = set(requested or [])
    allowed = ["name"]

    for field in meta.fields:
        fieldname = field.fieldname
        if not fieldname or field.fieldtype in {"Section Break", "Column Break", "Tab Break", "HTML", "Button"}:
            continue
        if requested_set and fieldname not in requested_set:
            continue
        if _is_sensitive(fieldname, field.label):
            continue
        if fieldname in TECHNICAL_FIELDS and fieldname not in requested_set:
            continue
        if field.hidden and fieldname not in requested_set:
            continue
        if not _can_read_permlevel(meta, field.permlevel, user):
            continue
        allowed.append(fieldname)
    return list(dict.fromkeys(allowed))


def get_writable_fields(doctype, requested_fields=None, user=None):
    user = user or frappe.session.user
    meta = frappe.get_meta(doctype)
    requested = set(requested_fields or [])
    roles = set(frappe.get_roles(user))
    allowed = []
    for field in meta.fields:
        if not field.fieldname or field.fieldname not in requested:
            continue
        if field.fieldname in {"name", "owner", "docstatus", "creation", "modified", "modified_by", "idx"}:
            continue
        if field.read_only or field.hidden or _is_sensitive(field.fieldname, field.label):
            continue
        if int(field.permlevel or 0) and not any(p.role in roles and int(p.permlevel or 0) == int(field.permlevel) and p.write for p in meta.permissions):
            continue
        allowed.append(field.fieldname)
    return allowed


def filter_output_fields(doctype, records, allowed_fields):
    del doctype
    allowed = set(allowed_fields or ["name"])
    if isinstance(records, dict):
        return {key: value for key, value in records.items() if key in allowed}
    return [{key: value for key, value in record.items() if key in allowed} for record in (records or [])]
