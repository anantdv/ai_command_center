import re

import bleach
import frappe
from frappe.utils import strip_html, validate_email_address

from ai_command_center.api.audit import log_ai_action
from ai_command_center.utils.response import error, safe_api, success

ALLOWED_TAGS=["p","br","strong","b","em","i","u","ul","ol","li","a","blockquote","code","pre","h1","h2","h3","table","thead","tbody","tr","th","td"]
MANAGER_ROLES={"System Manager","Communication Manager"}


def _clean_html(value): return bleach.clean(value or "",tags=ALLOWED_TAGS,attributes={"a":["href","title"]},protocols=["http","https","mailto"],strip=True)
def _emails(value): return {item.lower() for item in re.split(r"[,;\s]+",value or "") if "@" in item}
def _identity():
    user=frappe.session.user
    email=frappe.db.get_value("User",user,"email") or user
    return user,{user.lower(),str(email).lower()}
def _manager(user): return bool(MANAGER_ROLES.intersection(frappe.get_roles(user)))


def _reference_permission(doctype,name,ptype="read"):
    if not doctype or not name:return False
    return bool(frappe.has_permission(doctype=doctype,ptype=ptype,doc=name,user=frappe.session.user))


def _can_access(row,ptype="read"):
    user,identities=_identity()
    if _manager(user):return True
    ref_dt=row.get("reference_doctype");ref_name=row.get("reference_name")
    if ref_dt and ref_name:return _reference_permission(ref_dt,ref_name,ptype)
    parties=_emails(row.get("sender"))|_emails(row.get("recipients"))|_emails(row.get("cc"))
    return row.get("owner")==user or bool(identities.intersection(parties))


def _attachments(name):
    if not frappe.has_permission("File","read"):return []
    rows=frappe.db.get_list("File",filters={"attached_to_doctype":"Communication","attached_to_name":name},fields=["name","file_name","file_url","is_private"],limit_page_length=100)
    return [row for row in rows if frappe.get_doc("File",row.name).has_permission("read")]


def _serialize(row,detail=False):
    data=dict(row)
    content=_clean_html(data.pop("content","") or "")
    data["preview"]=(strip_html(content) or "")[:180]
    data["unread"]=not bool(data.pop("read_by_recipient",0)) if data.get("sent_or_received")=="Received" else False
    attachments=_attachments(data["name"])
    data["has_attachment"]=bool(attachments)
    data["creation"]=str(data.get("creation") or "")
    if detail:data["content"]=content;data["attachments"]=attachments
    return data


@frappe.whitelist()
@safe_api
def get_communications(filters=None,limit=20,start=0):
    if frappe.session.user=="Guest":frappe.throw("Login required.",frappe.AuthenticationError)
    filters=frappe.parse_json(filters) if isinstance(filters,str) else (filters or {})
    folder=filters.pop("folder","inbox");search=(filters.pop("search",None) or "").strip();limit=max(1,min(int(limit or 20),100));start=max(0,int(start or 0))
    query={"communication_medium":"Email"}
    if folder=="sent":query["sent_or_received"]="Sent"
    elif folder in {"inbox","unread"}:query["sent_or_received"]="Received"
    if filters.get("unread"):query["read_by_recipient"]=0
    if filters.get("reference_doctype"):query["reference_doctype"]=filters["reference_doctype"]
    if filters.get("linked") is True:query["reference_name"]=["is","set"]
    elif filters.get("linked") is False:query["reference_name"]=["is","not set"]
    fields=["name","subject","sender","recipients","cc","communication_type","sent_or_received","reference_doctype","reference_name","creation","status","content","owner","read_by_recipient"]
    kwargs={"doctype":"Communication","filters":query,"fields":fields,"order_by":"creation desc","limit_start":0,"limit_page_length":min(start+limit+200,500)}
    if search:kwargs["or_filters"]={"subject":["like",f"%{search}%"],"content":["like",f"%{search}%"],"sender":["like",f"%{search}%"]}
    rows=frappe.db.get_list(**kwargs)
    allowed=[_serialize(row) for row in rows if _can_access(row)]
    if filters.get("has_attachments"):allowed=[row for row in allowed if row["has_attachment"]]
    return success({"items":allowed[start:start+limit],"total":len(allowed)})


@frappe.whitelist()
@safe_api
def get_communication_thread(communication_name=None,reference_doctype=None,reference_name=None):
    if communication_name:
        anchor=frappe.get_doc("Communication",communication_name).as_dict()
        if not _can_access(anchor):frappe.throw("Communication access denied.",frappe.PermissionError)
        reference_doctype=reference_doctype or anchor.get("reference_doctype");reference_name=reference_name or anchor.get("reference_name")
    else:anchor={}
    if reference_doctype and reference_name:
        if not _reference_permission(reference_doctype,reference_name,"read"):frappe.throw("Linked document access denied.",frappe.PermissionError)
        rows=frappe.db.get_list("Communication",filters={"communication_medium":"Email","reference_doctype":reference_doctype,"reference_name":reference_name},fields=["name","subject","sender","recipients","cc","communication_type","sent_or_received","reference_doctype","reference_name","creation","status","content","owner","read_by_recipient"],order_by="creation asc",limit_page_length=200)
    else:rows=[anchor]
    messages=[_serialize(row,True) for row in rows if row and _can_access(row)]
    return success({"thread_id":anchor.get("subject") or f"{reference_doctype}/{reference_name}","reference_doctype":reference_doctype,"reference_name":reference_name,"messages":messages})


def _validate_reference(doctype,name,ptype):
    if bool(doctype)!=bool(name):frappe.throw("Both reference DocType and name are required.",frappe.ValidationError)
    if doctype and not _reference_permission(doctype,name,ptype):frappe.throw(f"You cannot {ptype} the linked document.",frappe.PermissionError)


def _validated_addresses(value):
    value=frappe.parse_json(value) if isinstance(value,str) else (value or [])
    addresses=[]
    for item in value:
        address=validate_email_address(str(item),throw=True)
        if address:addresses.append(address)
    return addresses


def _validated_files(values):
    values=frappe.parse_json(values) if isinstance(values,str) else (values or [])
    output=[]
    for name in values:
        file=frappe.get_doc("File",name)
        if not file.has_permission("read"):frappe.throw("Attachment access denied.",frappe.PermissionError)
        output.append({"file_url":file.file_url})
    return output


@frappe.whitelist()
@safe_api
def send_email(to,subject,content,cc=None,bcc=None,reference_doctype=None,reference_name=None,attachments=None):
    if not frappe.has_permission("Communication","create"):frappe.throw("You cannot create Communications.",frappe.PermissionError)
    _validate_reference(reference_doctype,reference_name,"write")
    recipients=_validated_addresses(to);cc=_validated_addresses(cc);bcc=_validated_addresses(bcc)
    if not recipients:frappe.throw("At least one valid recipient is required.",frappe.ValidationError)
    content=_clean_html(content);subject=(subject or "").strip()[:500]
    doc=frappe.new_doc("Communication");doc.update({"subject":subject,"sender":frappe.session.user,"recipients":", ".join(recipients),"cc":", ".join(cc),"bcc":", ".join(bcc),"content":content,"communication_type":"Communication","communication_medium":"Email","sent_or_received":"Sent","reference_doctype":reference_doctype,"reference_name":reference_name,"status":"Linked" if reference_name else "Open"});doc.insert()
    frappe.sendmail(recipients=recipients,subject=subject,message=content,cc=cc,bcc=bcc,reference_doctype=reference_doctype,reference_name=reference_name,attachments=_validated_files(attachments),communication=doc.name)
    log_ai_action(frappe.session.user,"send_email","Communication",doc.name,True,{"recipient_count":len(recipients)})
    return success({"name":doc.name,"doctype":"Communication","message":"Email queued successfully."})


@frappe.whitelist()
@safe_api
def reply_to_communication(communication_name,content,cc=None,bcc=None,attachments=None):
    original=frappe.get_doc("Communication",communication_name).as_dict()
    if not _can_access(original):frappe.throw("Communication access denied.",frappe.PermissionError)
    recipient=original.sender if original.sent_or_received=="Received" else original.recipients
    return send_email(list(_emails(recipient)),original.subject if original.subject.lower().startswith("re:") else f"Re: {original.subject}",content,cc,bcc,original.reference_doctype,original.reference_name,attachments)


@frappe.whitelist()
@safe_api
def forward_communication(communication_name,to,content=None,cc=None,bcc=None):
    original=frappe.get_doc("Communication",communication_name).as_dict()
    if not _can_access(original):frappe.throw("Communication access denied.",frappe.PermissionError)
    body=_clean_html(content or "")+"<hr><p><strong>Forwarded message</strong></p>"+_clean_html(original.content)
    return send_email(to,original.subject if original.subject.lower().startswith("fwd:") else f"Fwd: {original.subject}",body,cc,bcc,original.reference_doctype,original.reference_name,None)


@frappe.whitelist()
@safe_api
def get_email_templates():
    if not frappe.has_permission("Email Template","read"):frappe.throw("Email Template access denied.",frappe.PermissionError)
    return success(frappe.db.get_list("Email Template",fields=["name","subject","response"],order_by="name asc",limit_page_length=200))


@frappe.whitelist()
@safe_api
def render_email_template(template_name,context=None):
    doc=frappe.get_doc("Email Template",template_name)
    if not doc.has_permission("read"):frappe.throw("Email Template access denied.",frappe.PermissionError)
    context=frappe.parse_json(context) if isinstance(context,str) else (context or {})
    return success({"name":doc.name,"subject":frappe.render_template(doc.subject or "",context),"response":_clean_html(frappe.render_template(doc.response or "",context))})


@frappe.whitelist()
@safe_api
def link_communication(communication_name,reference_doctype,reference_name):
    doc=frappe.get_doc("Communication",communication_name)
    if not _can_access(doc.as_dict(),"write"):frappe.throw("Communication write access denied.",frappe.PermissionError)
    _validate_reference(reference_doctype,reference_name,"write");doc.reference_doctype=reference_doctype;doc.reference_name=reference_name;doc.save()
    return success({"name":doc.name,"doctype":"Communication","message":f"Linked to {reference_doctype} {reference_name}."})


@frappe.whitelist()
@safe_api
def create_ai_mail_draft(communication_name=None,instruction=None,content=None):
    if communication_name:
        doc=frappe.get_doc("Communication",communication_name)
        if not _can_access(doc.as_dict()):frappe.throw("Communication access denied.",frappe.PermissionError)
    instruction=(instruction or "Draft Reply")[:100]
    draft=_clean_html(content or "<p>Thank you for your email. We are reviewing your request and will respond shortly.</p>")
    return success({"action":instruction,"content":draft,"requires_review":True})


def _conversion_source(name):
    doc=frappe.get_doc("Communication",name)
    if not _can_access(doc.as_dict()):frappe.throw("Communication access denied.",frappe.PermissionError)
    return doc
def _conversion_result(doc):return success({"name":doc.name,"doctype":doc.doctype,"message":f"{doc.doctype} {doc.name} created."})


@frappe.whitelist()
@safe_api
def convert_email_to_task(communication_name):
    source=_conversion_source(communication_name)
    if not frappe.has_permission("Task","create"):frappe.throw("Task create permission denied.",frappe.PermissionError)
    doc=frappe.new_doc("Task");doc.subject=(source.subject or "Email task")[:140];doc.description=_clean_html(source.content);doc.insert();return _conversion_result(doc)


@frappe.whitelist()
@safe_api
def convert_email_to_issue(communication_name):
    source=_conversion_source(communication_name)
    if not frappe.has_permission("Issue","create"):frappe.throw("Issue create permission denied.",frappe.PermissionError)
    doc=frappe.new_doc("Issue");doc.subject=(source.subject or "Email issue")[:140];doc.description=_clean_html(source.content);doc.raised_by=next(iter(_emails(source.sender)),frappe.session.user);doc.insert();return _conversion_result(doc)


@frappe.whitelist()
@safe_api
def convert_email_to_lead(communication_name):
    source=_conversion_source(communication_name)
    if not frappe.has_permission("Lead","create"):frappe.throw("Lead create permission denied.",frappe.PermissionError)
    email=next(iter(_emails(source.sender)),"");doc=frappe.new_doc("Lead");doc.lead_name=(source.sender or source.subject or "Email Lead")[:140];doc.email_id=email;doc.source="Email" if doc.meta.has_field("source") else None;doc.notes=_clean_html(source.content) if doc.meta.has_field("notes") else None;doc.insert();return _conversion_result(doc)
