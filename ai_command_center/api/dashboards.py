import frappe

from ai_command_center.api.crud import list_records
from ai_command_center.api.reports import run_report
from ai_command_center.utils.permission_guard import guard_action
from ai_command_center.utils.response import error, safe_api, success


@frappe.whitelist()
@safe_api
def get_widget_data(source_type, source_name=None, doctype=None, filters=None, chart_config=None):
    source_type = str(source_type or "").lower()
    if source_type == "doctype":
        if not doctype:
            frappe.throw("doctype is required for a DocType widget.", frappe.ValidationError)
        result = list_records(doctype, filters=filters, limit=500)
    elif source_type == "report":
        if not source_name:
            frappe.throw("source_name is required for a Report widget.", frappe.ValidationError)
        result = run_report(source_name, filters)
    else:
        frappe.throw("source_type must be DocType or Report.", frappe.ValidationError)
    if not result.get("success"):
        return result
    return success({"source_type": source_type, "source_name": source_name or doctype, "data": result["data"], "chart_config": frappe.parse_json(chart_config) if isinstance(chart_config, str) else (chart_config or {})})


@frappe.whitelist()
@safe_api
def save_dashboard_widget(dashboard_name, widget_config):
    config = frappe.parse_json(widget_config) if isinstance(widget_config, str) else (widget_config or {})
    guard = guard_action("AI Dashboard Widget", action="create", payload=config)
    if not guard["allowed"]:
        return error(guard["reason"])
    if not frappe.db.exists("AI Dashboard", dashboard_name):
        frappe.throw("Dashboard does not exist.", frappe.DoesNotExistError)
    dashboard = frappe.get_doc("AI Dashboard", dashboard_name)
    if not dashboard.has_permission("write"):
        frappe.throw("Dashboard write permission denied.", frappe.PermissionError)
    allowed = {"widget_title", "widget_type", "source_type", "source_doctype", "source_report", "filters_json", "chart_config_json", "refresh_interval", "position_x", "position_y", "width", "height"}
    doc = frappe.new_doc("AI Dashboard Widget")
    doc.dashboard = dashboard_name
    for key, value in config.items():
        if key in allowed:
            doc.set(key, value)
    doc.insert()
    return success({"name": doc.name}, "Dashboard widget saved")
