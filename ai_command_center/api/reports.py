import frappe

from ai_command_center.api.audit import log_ai_action
from ai_command_center.utils.permission_guard import guard_action
from ai_command_center.utils.response import error, safe_api, success

MAX_REPORT_ROWS = 500


def _allowed_report_doc(report_name):
    report = frappe.get_doc("Report", report_name)
    if report.report_type not in {"Script Report", "Query Report"}:
        frappe.throw("Only existing Script and Query Reports are supported.", frappe.ValidationError)
    if not report.has_permission("read"):
        frappe.throw("You do not have access to this report.", frappe.PermissionError)
    if report.ref_doctype and not frappe.has_permission(report.ref_doctype, "report"):
        frappe.throw("You do not have report permission for the reference DocType.", frappe.PermissionError)
    return report


@frappe.whitelist()
@safe_api
def get_allowed_reports(module=None):
    filters = {"disabled": 0}
    if module:
        filters["module"] = module
    rows = frappe.db.get_list("Report", filters=filters, fields=["name", "report_name", "report_type", "ref_doctype", "module"], limit_page_length=500)
    allowed = []
    for row in rows:
        try:
            _allowed_report_doc(row.name)
            allowed.append(row)
        except (frappe.PermissionError, frappe.ValidationError):
            continue
    return success(allowed)


@frappe.whitelist()
@safe_api
def run_report(report_name, filters=None):
    report = _allowed_report_doc(report_name)
    guard = guard_action(report.ref_doctype, action="report") if report.ref_doctype else {"allowed": True, "risk_level": "low"}
    if not guard["allowed"]:
        return error(guard["reason"], {"report": report_name})
    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    from frappe.desk.query_report import run
    output = run(report_name, filters=filters)
    rows = output.get("result") or []
    output["result"] = rows[:MAX_REPORT_ROWS]
    output["truncated"] = len(rows) > MAX_REPORT_ROWS
    log_ai_action(frappe.session.user, "report", report.ref_doctype, details={"risk_level": "low", "output_summary": f"{len(output['result'])} rows"})
    return success({"columns": output.get("columns", []), "rows": output["result"], "chart": output.get("chart"), "report_summary": output.get("report_summary"), "truncated": output["truncated"]})
