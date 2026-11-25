// One structured-output call: category + fields, strict JSON schema.
const SYSTEM = %%SYSTEM%%;
const SCHEMA = %%SCHEMA%%;
const e = $json;
return {
  json: {
    ...e,
    openai_request: {
      model: "%%MODEL%%",
      temperature: 0,
      response_format: { type: "json_schema", json_schema: { name: "triage", strict: true, schema: SCHEMA } },
      messages: [
        { role: "system", content: SYSTEM },
        { role: "user", content: `Received: ${e.received_at}\nFrom: ${e.from_name} <${e.from_addr}>\nSubject: ${e.subject}\n\n${e.body}` },
      ],
    },
  },
};
