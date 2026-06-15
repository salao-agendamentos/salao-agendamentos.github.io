# Salão — Sistema de Agendamentos (SaaS)

Sistema de agendamento online multi-salão. Cada salão cria sua conta, tem seus dados
isolados e seu próprio link para as clientes. Lembrete por e-mail automático.

## Estrutura
- `index.html` — o app (site + painel do salão)
- `.github/scripts/lembrete.mjs` — script que envia os lembretes
- `.github/workflows/lembrete.yml` — agenda o lembrete a cada 15 min (grátis no GitHub Actions)
- `firestore.rules` — regras de segurança do banco

## Como funciona
- **Dono do salão:** acessa o site, faz login → vê Agenda, Dashboard, Ajustes.
- **Cliente:** acessa o link `...?s=ID_DO_SALAO` → vê só a tela de agendar.
- **Lembrete:** o GitHub Actions roda sozinho a cada 15 min, encontra quem tem horário
  na próxima hora e dispara o e-mail.

## Deploy (uma vez)

### 1. GitHub Pages (hospeda o site)
1. Suba estes arquivos para um repositório no GitHub.
2. Settings → Pages → Source: **Deploy from a branch** → branch `main` / pasta `/ (root)` → Save.
3. Em ~1 min o site fica em `https://SEU_USUARIO.github.io/NOME_DO_REPO/`.

### 2. Secrets (chaves seguras para o lembrete)
Settings → Secrets and variables → **Actions** → New repository secret. Crie 4:
- `FB_PROJECT_ID` → `salaoagendamentos-d15d0`
- `FB_API_KEY` → a apiKey do Firebase
- `RESEND_API_KEY` → a chave do Resend (`re_...`)
- `REMETENTE` → `Salão <onboarding@resend.dev>` (ou seu domínio verificado no Resend)

### 3. Ativar o Actions
Aba **Actions** → habilite os workflows → abra "Lembrete de agendamentos" →
botão **Run workflow** para testar na hora. Depois ele roda sozinho a cada 15 min.

### 4. Firebase (uma vez)
- Authentication → Sign-in method → habilite **E-mail/senha**.
- Firestore → Regras → cole o conteúdo de `firestore.rules` → Publicar.

## Novo cliente (salão)
Manda o link do site. Ele clica em "Criar conta gratuita", informa nome + e-mail + senha,
e já está no ar. Em Ajustes ele copia o "Meu link" e divulga para as clientes dele.
Você não precisa fazer mais nada.
