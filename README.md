# AI Command Center — Frappe Companion App

Secure, permission-aware ERPNext gateway for the ERP AI Command Center. The app exposes narrowly scoped whitelisted methods while preserving the logged-in user's roles, User Permissions, record permissions, field permlevels, workflow constraints, and normal document validation.

## Security model

- No `ignore_permissions=True`.
- No raw SQL or unrestricted database query API.
- User-facing lists use `frappe.db.get_list`, which applies Frappe permissions and User Permissions.
- Reads use `frappe.get_doc` and document-level permission checks.
- Creates remain Draft and use normal `insert()` validation.
- Updates use writable field allowlists and normal `save()` validation.
- Delete is high risk and requires a matching one-time server-side confirmation token.
- Sensitive fields and unreadable permlevels are removed before output.
- Existing reports require Report access and report permission on the reference DocType.
- Blocked system DocTypes are unavailable unless the user is a System Manager.
- API keys must belong to the actual user or a strictly permissioned integration user—never Administrator.
- External audit event registration is restricted to System Manager and AI Command Center Manager; normal API actions write their own audit records in the active user's context.

Field-level checks deliberately fail closed. Nonzero permlevel fields are exposed only when a matching readable role permission is present in the DocType metadata. Production deployments should review Custom DocPerm behavior for their site before enabling AI write actions.

## Installation

```bash
cd frappe-bench
bench get-app /path/to/ai_command_center
bench --site yoursite.local install-app ai_command_center
bench --site yoursite.local migrate
bench clear-cache
bench restart
```

The Python project name must remain `ai_command_center` (with underscores). Bench uses
this value as the app directory and asset-build identifier. Keep `hooks.py`, `modules.txt`,
and `patches.txt` in the Python package because Frappe's asset builder uses them to
recognize the directory as a Frappe app.

### Recovering from the pre-0.1.1 hyphenated package name

If an earlier `bench get-app` renamed the directory to `apps/ai-command-center`, update
and normalize it before retrying the build:

```bash
cd frappe-bench/apps/ai-command-center
git pull upstream main
cd ../..
mv apps/ai-command-center apps/ai_command_center
sed -i 's/^ai-command-center$/ai_command_center/' sites/apps.txt
grep -qxF 'ai_command_center' sites/apps.txt || printf '%s\n' 'ai_command_center' >> sites/apps.txt
uv pip install --upgrade -e apps/ai_command_center --python env/bin/python
bench build --app ai_command_center
```

Assign one or more roles after installation:

- AI Command Center Manager
- AI Command Center User
- AI Training Manager
- AI Support Agent

## Development updates

```bash
cd apps/ai_command_center
git pull
cd ../..
bench --site yoursite.local migrate
bench --site yoursite.local clear-cache
bench restart
```

## Bench console checks

```bash
bench --site yoursite.local execute ai_command_center.api.auth.get_current_user_context
bench --site yoursite.local execute ai_command_center.api.schema.get_allowed_doctypes
bench --site yoursite.local execute ai_command_center.api.crud.list_records --kwargs "{'doctype':'Customer','fields':['name','customer_name'],'limit':10}"
```

HTTP methods are available at `/api/method/<method-path>`:

```text
ai_command_center.api.auth.get_current_user_context
ai_command_center.api.schema.get_allowed_modules
ai_command_center.api.schema.get_allowed_doctypes
ai_command_center.api.schema.get_doctype_schema
ai_command_center.api.permissions.check_permission
ai_command_center.api.permissions.explain_permission_denial
ai_command_center.api.crud.list_records
ai_command_center.api.crud.get_record
ai_command_center.api.crud.create_record
ai_command_center.api.crud.update_record
ai_command_center.api.crud.delete_record
ai_command_center.api.reports.run_report
ai_command_center.api.reports.get_allowed_reports
ai_command_center.api.dashboards.get_widget_data
ai_command_center.api.dashboards.save_dashboard_widget
ai_command_center.api.files.register_generated_file
ai_command_center.api.files.list_generated_files
ai_command_center.api.support.create_support_ticket
ai_command_center.api.support.list_support_tickets
ai_command_center.api.audit.create_audit_log
ai_command_center.api.communications.get_communications
ai_command_center.api.communications.get_communication_thread
ai_command_center.api.communications.send_email
ai_command_center.api.communications.reply_to_communication
ai_command_center.api.communications.forward_communication
ai_command_center.api.communications.get_email_templates
ai_command_center.api.communications.render_email_template
ai_command_center.api.communications.link_communication
ai_command_center.api.communications.create_ai_mail_draft
ai_command_center.api.communications.convert_email_to_task
ai_command_center.api.communications.convert_email_to_issue
ai_command_center.api.communications.convert_email_to_lead
```

## Communication Center

Communication APIs use the standard `Communication`, `Email Template`, `Email Queue`, and `File` DocTypes. Linked messages require permission on the referenced document; unlinked messages are limited to involved users or communication managers. Sending uses `frappe.sendmail`, queues mail through configured ERPNext Email Accounts, sanitizes HTML, validates recipients and attachments, and records an audit event. AI draft endpoints return previews only and never send automatically.

## Confirmation tokens

Deletion consumes a one-time value from this server-side cache key:

```text
ai_cc_confirmation:{user}:{doctype}:{record_name}:delete
```

The FastAPI safety workflow should generate a cryptographically random token, store it with a short TTL, present the action summary to the user, and only then call `delete_record`. Arbitrary client-provided tokens are rejected.

## FastAPI configuration

Point the FastAPI connector at the ERPNext site and forward the authenticated user's `sid`, or use API credentials belonging to that user. Companion method calls are documented in the FastAPI backend README.

## Next steps

1. Add integration tests inside a disposable Frappe v15 and v16 bench.
2. Add a short-lived confirmation-token issue endpoint owned by the FastAPI safety workflow.
3. Add workflow transition previews before submit/cancel support.
4. Add retention policies for messages, files, and audit logs.
5. Review site-specific Custom DocPerm and sensitive-field policy before production rollout.
