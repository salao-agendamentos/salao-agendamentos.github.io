const PROJECT_ID = process.env.FB_PROJECT_ID;
const API_KEY    = process.env.FB_API_KEY;
const RESEND_KEY = process.env.RESEND_API_KEY;
const REMETENTE  = process.env.REMETENTE || "Salão <onboarding@resend.dev>";

if (!PROJECT_ID || !API_KEY || !RESEND_KEY) {
  console.error("Faltam variáveis: FB_PROJECT_ID, FB_API_KEY, RESEND_API_KEY");
  process.exit(1);
}

const FS = `https://firestore.googleapis.com/v1`;
const agora = Date.now();
const de  = agora + 45 * 60 * 1000;
const ate = agora + 75 * 60 * 1000;

async function buscar() {
  const body = {
    structuredQuery: {
      from: [{ collectionId: "agendamentos", allDescendants: true }],
      where: {
        compositeFilter: {
          op: "AND",
          filters: [
            { fieldFilter: { field: { fieldPath: "startTs" }, op: "GREATER_THAN_OR_EQUAL", value: { integerValue: String(de) } } },
            { fieldFilter: { field: { fieldPath: "startTs" }, op: "LESS_THAN_OR_EQUAL",    value: { integerValue: String(ate) } } },
          ],
        },
      },
    },
  };
  const res = await fetch(`${FS}/projects/${PROJECT_ID}/databases/(default)/documents:runQuery?key=${API_KEY}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const json = await res.json();
  return Array.isArray(json) ? json.filter(r => r.document) : [];
}

async function enviarEmail({ to, subject, html }) {
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${RESEND_KEY}` },
    body: JSON.stringify({ from: REMETENTE, to: [to], subject, html }),
  });
  if (!res.ok) throw new Error(`Resend ${res.status}: ${await res.text()}`);
}

async function marcar(docName) {
  await fetch(`${FS}/${docName}?updateMask.fieldPaths=reminded&key=${API_KEY}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields: { reminded: { booleanValue: true } } }),
  });
}

function val(f, k) { return (f[k] && (f[k].stringValue ?? f[k].integerValue ?? f[k].booleanValue)) ?? ""; }

(async () => {
  const rows = await buscar();
  console.log(`Encontrados ${rows.length} agendamento(s) na janela.`);
  let enviados = 0;

  for (const r of rows) {
    const doc = r.document;
    const f = doc.fields || {};

    if (val(f, "status") && val(f, "status") !== "agendado") continue;
    if (f.reminded && f.reminded.booleanValue === true) continue;

    const email = val(f, "email");
    if (!email || !String(email).includes("@")) continue;

    const cliente   = val(f, "cliente") || "cliente";
    const endereco  = val(f, "endereco") || "";
    const salonName = val(f, "salonName") || "Salão";
    const inicio    = Number(val(f, "inicio") || 0);
    const hh = String(Math.floor(inicio / 60)).padStart(2, "0");
    const mm = String(inicio % 60).padStart(2, "0");
    const hora = hh + ":" + mm;
    const svcs = (f.servicos?.arrayValue?.values || [])
      .map(v => v.mapValue?.fields?.nome?.stringValue || "")
      .filter(Boolean).join(", ");

    const linhaServico = svcs ? "<p>Serviço: " + svcs + "</p>" : "";
    const linhaEndereco = endereco ? "<p>📍 " + endereco + "</p>" : "";
    const html =
      "<!DOCTYPE html><html><body style=\"font-family:sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#3a2b2e\">" +
      "<h2 style=\"color:#c0788a\">Lembrete do seu horário</h2>" +
      "<p>Oi <strong>" + cliente + "</strong>! Seu horário no <strong>" + salonName + "</strong> é <strong>hoje às " + hora + "</strong>.</p>" +
      linhaServico +
      linhaEndereco +
      "<p style=\"margin-top:20px;color:#9c8088;font-size:13px\">Te esperamos!</p>" +
      "</body></html>";

    const subject = "Lembrete: seu horário no " + salonName + " hoje às " + hora;

    try {
      await enviarEmail({ to: email, subject, html });
      await marcar(doc.name);
      enviados++;
      console.log("Enviado para " + email + " (" + hora + ")");
    } catch (e) {
      console.error("Falha para " + email + ":", e.message);
    }
  }
  console.log("Concluido. " + enviados + " e-mail(s) enviado(s).");
})();
