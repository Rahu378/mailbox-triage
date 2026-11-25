// IMAP trigger output ("simple" format) -> the email shape everything else uses.
const j = $json;
const fromText = (j.from && (j.from.text || j.from.value?.[0]?.address || j.from)) || "";
const m = String(fromText).match(/^\s*"?(.*?)"?\s*<([^>]+)>\s*$/);
const strip = (html) => String(html || "")
  .replace(/<style[\s\S]*?<\/style>/gi, "")
  .replace(/<br\s*\/?>/gi, "\n").replace(/<\/p>/gi, "\n")
  .replace(/<[^>]+>/g, "").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&");
const body = (j.textPlain || strip(j.textHtml) || "").replace(/\r\n/g, "\n").trim();
return {
  json: {
    email_id: j.messageId || j.metadata?.["message-id"] || `IMAP-${$execution.id}-${$itemIndex}`,
    received_at: new Date(j.date || Date.now()).toISOString(),
    from_name: m ? m[1] : "",
    from_addr: (m ? m[2] : String(fromText)).trim().toLowerCase(),
    subject: j.subject || "",
    body: body.slice(0, 20000),
    attachments: (j.attachments || []).map((a) => a.filename).filter(Boolean),
  },
};
