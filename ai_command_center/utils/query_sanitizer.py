import json
import re

import frappe

from ai_command_center.utils.constants import ALLOWED_FILTER_OPERATORS, MAX_LIST_LIMIT

ORDER_PATTERN = re.compile(r"^[a-zA-Z0-9_]+(?:\s+(?:asc|desc))?$", re.IGNORECASE)


def _valid_fields(doctype):
    meta = frappe.get_meta(doctype)
    standard_fields = {"name", "owner", "modified_by", "creation", "modified", "docstatus", "idx"}
    return {*standard_fields, *[field.fieldname for field in meta.fields if field.fieldname]}


def sanitize_fields(doctype, fields):
    fields = frappe.parse_json(fields) if isinstance(fields, str) else fields
    if fields is None:
        return ["name"]
    if not isinstance(fields, (list, tuple)):
        frappe.throw("Fields must be a JSON array.", frappe.ValidationError)
    valid = _valid_fields(doctype)
    cleaned = [field for field in fields if isinstance(field, str) and field in valid]
    if len(cleaned) != len(fields):
        frappe.throw("One or more requested fields are invalid.", frappe.ValidationError)
    return list(dict.fromkeys(["name", *cleaned]))


def sanitize_filters(doctype, filters):
    filters = frappe.parse_json(filters) if isinstance(filters, str) else filters
    if not filters:
        return []
    valid = _valid_fields(doctype)
    if isinstance(filters, dict):
        if any(field not in valid for field in filters):
            frappe.throw("Filter contains an invalid field.", frappe.ValidationError)
        for value in filters.values():
            _validate_filter_value(value)
        return filters
    if not isinstance(filters, (list, tuple)):
        frappe.throw("Filters must be a JSON object or array.", frappe.ValidationError)
    cleaned = []
    for item in filters:
        if not isinstance(item, (list, tuple)) or len(item) not in {3, 4}:
            frappe.throw("Invalid filter structure.", frappe.ValidationError)
        field_index = 1 if len(item) == 4 else 0
        operator_index = field_index + 1
        if item[field_index] not in valid or str(item[operator_index]).lower() not in ALLOWED_FILTER_OPERATORS:
            frappe.throw("Filter field or operator is not allowed.", frappe.ValidationError)
        if len(item) == 4 and item[0] != doctype:
            frappe.throw("Cross-DocType filters are not allowed.", frappe.ValidationError)
        _validate_operator_value(str(item[operator_index]).lower(), item[operator_index + 1])
        cleaned.append(list(item))
    return cleaned


def _validate_filter_value(value):
    _ensure_json_compatible(value)
    if isinstance(value, (list, tuple)):
        if len(value) != 2 or not isinstance(value[0], str):
            frappe.throw("Invalid filter operator value.", frappe.ValidationError)
        operator = value[0].lower()
        if operator not in ALLOWED_FILTER_OPERATORS:
            frappe.throw("Filter operator is not allowed.", frappe.ValidationError)
        _validate_operator_value(operator, value[1])
    elif isinstance(value, dict):
        frappe.throw("Nested filter objects are not allowed.", frappe.ValidationError)


def _validate_operator_value(operator, value):
    _ensure_json_compatible(value)
    if operator in {"in", "not in", "between"} and not isinstance(value, (list, tuple)):
        frappe.throw(f"The {operator} operator requires an array value.", frappe.ValidationError)
    if operator == "between" and len(value) != 2:
        frappe.throw("The between operator requires exactly two values.", frappe.ValidationError)


def _ensure_json_compatible(value):
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        frappe.throw("Filter values must be JSON-compatible.", frappe.ValidationError)


def sanitize_limit(limit, default=20, maximum=MAX_LIST_LIMIT):
    try:
        value = int(limit or default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


def sanitize_order_by(doctype, order_by):
    if not order_by:
        return "modified desc"
    if not isinstance(order_by, str) or not ORDER_PATTERN.fullmatch(order_by.strip()):
        frappe.throw("Invalid order_by value.", frappe.ValidationError)
    fieldname = order_by.strip().split()[0]
    if fieldname not in _valid_fields(doctype):
        frappe.throw("order_by field is not valid for this DocType.", frappe.ValidationError)
    return order_by.strip()
