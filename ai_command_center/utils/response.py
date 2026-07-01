from functools import wraps

import frappe


def success(data=None, message=None):
    return {"success": True, "data": data, "message": message}


def error(message, details=None):
    return {"success": False, "message": message, "details": details or {}}


def safe_api(function):
    """Prevent stack traces and internal exception details from reaching API clients."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (frappe.PermissionError, frappe.AuthenticationError) as exc:
            return error(str(exc) or "Permission denied")
        except (frappe.ValidationError, frappe.DoesNotExistError) as exc:
            return error(str(exc) or "Invalid request")
        except Exception:
            frappe.log_error(title=f"AI Command Center API: {function.__name__}", message=frappe.get_traceback())
            return error("The request could not be completed safely.")
    return wrapper
