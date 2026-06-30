#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Envio automático de lembretes por e-mail (≈1h antes do compromisso)
para o sistema de agendamentos do salão (Firebase / Firestore).

Como funciona:
  1. Conecta no Firestore usando uma conta de serviço (Admin SDK).
  2. Lê os agendamentos com status 'agendado'.
  3. Para cada um que começa dentro da próxima 1 hora, ainda NÃO foi
     lembrado e tem e-mail, dispara o lembrete.
  4. Marca o agendamento com reminded=true para nunca enviar duas vezes.

Foi feito para rodar de tempos em tempos (ex.: a cada 15 min) num "cron",
como o GitHub Actions. Não precisa ficar ligado o tempo todo.
"""

import os
import sys
import json
import smtplib
from string import Template
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from zoneinfo import ZoneInfo

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import FieldFilter


# ===================== CONFIGURAÇÃO (variáveis de ambiente) =====================
TZ           = ZoneInfo(os.environ.get("SALON_TZ", "America/Sao_Paulo"))
LEAD_MINUTES = int(os.environ.get("LEAD_MINUTES", "60"))   # avisar com quanto tempo de antecedência
SALON_ID     = os.environ.get("SALON_ID", "").strip()      # vazio = processa TODOS os salões
SALON_NAME_FALLBACK = os.environ.get("SALON_NAME", "Nosso salão")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
FROM_NAME = os.environ.get("FROM_NAME", "")                # nome amigável do remetente (opcional)

# DRY_RUN=1 -> só mostra o que faria, não envia nem marca nada (ótimo para testar)
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira",
               "quinta-feira", "sexta-feira", "sábado", "domingo"]


# ===================== FIREBASE =====================
def init_firestore():
    """Inicializa o Admin SDK. Aceita a chave via JSON (env) ou via arquivo."""
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if raw:
        cred = credentials.Certificate(json.loads(raw))
    else:
        path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if path and os.path.exists(path):
            cred = credentials.Certificate(path)
        else:
            sys.exit("ERRO: defina FIREBASE_SERVICE_ACCOUNT (conteúdo JSON da chave) "
                     "ou GOOGLE_APPLICATION_CREDENTIALS (caminho do arquivo).")
    firebase_admin.initialize_app(cred)
    return firestore.client()


def salon_ids(db):
    """Se SALON_ID estiver definido, usa só ele; senão, lista todos os salões."""
    if SALON_ID:
        return [SALON_ID]
    return [ref.id for ref in db.collection("saloes").list_documents()]


# ===================== AJUDANTES =====================
def appt_start_ms(appt):
    """
    Retorna o horário de início em milissegundos (epoch).
    Usa startTs quando existe; senão, reconstrói a partir de
    data ('AAAA-MM-DD') + inicio (minutos a partir da meia-noite local).
    """
    ts = appt.get("startTs")
    if isinstance(ts, (int, float)) and ts > 0:
        return int(ts)

    data, inicio = appt.get("data"), appt.get("inicio")
    if not data or inicio is None:
        return None
    try:
        y, m, d = (int(x) for x in data.split("-"))
        base = datetime(y, m, d, 0, 0, tzinfo=TZ) + timedelta(minutes=int(inicio))
        return int(base.timestamp() * 1000)
    except Exception:
        return None


# ===================== MONTAGEM DO E-MAIL =====================
HTML_TPL = Template("""\
<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#fbf5f1;font-family:Arial,Helvetica,sans-serif;color:#46333b">
  <div style="max-width:480px;margin:0 auto;padding:24px">
    <div style="background:#ffffff;border:1px solid #eedfd8;border-radius:16px;overflow:hidden">
      <div style="height:5px;background:linear-gradient(90deg,#d68fa0,#c9a96a,#b89bb6,#d68fa0)"></div>
      <div style="padding:28px 26px">
        <p style="margin:0 0 4px;letter-spacing:2px;text-transform:uppercase;font-size:12px;color:#c0788a">Lembrete de horário</p>
        <h1 style="margin:0 0 16px;font-size:22px;color:#46333b">$salao</h1>
        <p style="margin:0 0 18px;font-size:15px;line-height:1.5">Olá, <strong>$primeiro_nome</strong>! Passando para lembrar do seu horário, que é daqui a pouco.</p>
        <table style="width:100%;border-collapse:collapse;margin:0 0 18px">
          <tr>
            <td style="padding:9px 0;color:#9c8088;font-size:13px">Quando</td>
            <td style="padding:9px 0;text-align:right;font-weight:bold;font-size:15px">$dia_sem, $data_fmt</td>
          </tr>
          <tr>
            <td style="padding:9px 0;color:#9c8088;font-size:13px;border-top:1px solid #eedfd8">Horário</td>
            <td style="padding:9px 0;text-align:right;font-weight:bold;font-size:19px;color:#c0788a;border-top:1px solid #eedfd8">$hora</td>
          </tr>
          <tr>
            <td style="padding:9px 0;color:#9c8088;font-size:13px;border-top:1px solid #eedfd8">Serviço(s)</td>
            <td style="padding:9px 0;text-align:right;font-size:15px;border-top:1px solid #eedfd8">$servicos</td>
          </tr>
          $endereco_row
        </table>
        <p style="margin:0;font-size:13px;color:#9c8088;line-height:1.5">Precisa remarcar ou cancelar? É só responder este e-mail. Até logo!</p>
      </div>
    </div>
    <p style="text-align:center;color:#b9a3a9;font-size:11px;margin:14px 0 0">Você recebeu este lembrete porque agendou um horário no $salao.</p>
  </div>
</body>
</html>""")


def build_message(appt, to_email, start_ms):
    dt = datetime.fromtimestamp(start_ms / 1000, tz=TZ)
    hora      = dt.strftime("%H:%M")
    data_fmt  = dt.strftime("%d/%m/%Y")
    dia_sem   = DIAS_SEMANA[dt.weekday()]

    cliente   = (appt.get("cliente") or "Cliente").strip()
    primeiro  = cliente.split()[0] if cliente else "Cliente"
    salao     = (appt.get("salonName") or SALON_NAME_FALLBACK).strip()
    endereco  = (appt.get("endereco") or "").strip()
    servicos  = " + ".join(s.get("nome", "") for s in (appt.get("servicos") or []) if s.get("nome")) \
                or "Seu atendimento"

    endereco_row_html = ""
    if endereco:
        endereco_row_html = (
            '<tr><td style="padding:9px 0;color:#9c8088;font-size:13px;border-top:1px solid #eedfd8">Endereço</td>'
            f'<td style="padding:9px 0;text-align:right;font-size:14px;border-top:1px solid #eedfd8">{endereco}</td></tr>'
        )

    html = HTML_TPL.substitute(
        salao=salao, primeiro_nome=primeiro, dia_sem=dia_sem,
        data_fmt=data_fmt, hora=hora, servicos=servicos,
        endereco_row=endereco_row_html,
    )

    texto = (
        f"Olá, {primeiro}!\n\n"
        f"Lembrete do seu horário no {salao}.\n\n"
        f"Quando: {dia_sem}, {data_fmt}\n"
        f"Horário: {hora}\n"
        f"Serviço(s): {servicos}\n"
        + (f"Endereço: {endereco}\n" if endereco else "")
        + "\nPrecisa remarcar ou cancelar? É só responder este e-mail.\nAté logo!"
    )

    msg = EmailMessage()
    msg["Subject"] = f"Lembrete: seu horário às {hora} — {salao}"
    # Remetente: mostra o nome DO SALÃO de cada agendamento (multi-cliente).
    msg["From"] = formataddr((salao or FROM_NAME or "Agendamentos", SMTP_FROM))
    msg["To"] = to_email
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    return msg


def smtp_send(msg):
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.ehlo()
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)


# ===================== PROCESSAMENTO =====================
def process_salon(db, salon_id, now_ms):
    col = db.collection("saloes").document(salon_id).collection("agendamentos")
    docs = col.where(filter=FieldFilter("status", "==", "agendado")).stream()

    enviados = 0
    for doc in docs:
        a = doc.to_dict() or {}

        if a.get("reminded") is True:
            continue
        email = (a.get("email") or "").strip()
        if not email:
            continue

        start_ms = appt_start_ms(a)
        if start_ms is None:
            continue

        restante_min = (start_ms - now_ms) / 60000.0
        # janela: já passou? ignora. Falta mais que o limite? ainda não é hora.
        if restante_min <= 0 or restante_min > LEAD_MINUTES:
            continue

        try:
            msg = build_message(a, email, start_ms)
            if DRY_RUN:
                print(f"[DRY-RUN] enviaria para {email} ({a.get('cliente','')}) "
                      f"— faltam {restante_min:.0f} min — {salon_id}/{doc.id}")
            else:
                smtp_send(msg)
                doc.reference.update({"reminded": True, "remindedAt": now_ms})
                print(f"[OK] lembrete -> {email} ({a.get('cliente','')}) — {salon_id}/{doc.id}")
            enviados += 1
        except Exception as e:
            # Não marca reminded: na próxima rodada tenta de novo.
            print(f"[ERRO] {salon_id}/{doc.id} -> {e}")

    return enviados


def salon_ativo(db, salon_id):
    """Salão suspenso (assinaturas/{id}.ativo == False) é ignorado. Sem doc = ativo."""
    try:
        snap = db.collection("assinaturas").document(salon_id).get()
        if snap.exists:
            return (snap.to_dict() or {}).get("ativo", True) is not False
        return True
    except Exception:
        return True


def main():
    if not DRY_RUN and not all([SMTP_HOST, SMTP_USER, SMTP_PASS]):
        sys.exit("ERRO: configure SMTP_HOST, SMTP_USER e SMTP_PASS (ou use DRY_RUN=1 para testar).")

    db = init_firestore()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    agora_local = datetime.now(TZ).strftime("%d/%m %H:%M")

    alvos = salon_ids(db)
    print(f"== Lembretes | {agora_local} ({TZ.key}) | janela={LEAD_MINUTES}min | "
          f"salões={len(alvos)} | dry_run={DRY_RUN} ==")

    total = 0
    for sid in alvos:
        if not salon_ativo(db, sid):
            print(f"[SUSPENSO] salão {sid} ignorado (assinatura inativa).")
            continue
        total += process_salon(db, sid, now_ms)
    print(f"== Fim. {total} lembrete(s) processado(s). ==")


if __name__ == "__main__":
    main()
