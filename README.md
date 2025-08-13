# 📊 ERP KTB Portugal

Sistema de gestão de cotações desenvolvido em **Python** com **Streamlit** e **PostgreSQL** (Supabase), permitindo:
- Criar e gerir pedidos de cotação (RFQs)
- Responder cotações e enviar orçamentos
- Gerar PDFs automáticos (pedido e cliente)
- Configurar fornecedores, marcas e margens
- Enviar orçamentos por e-mail diretamente pelo sistema

---

## 📂 Estrutura do Projeto

.
├── main.py # Interface principal Streamlit e lógica de negócio
├── db.py # Funções de conexão e gestão da base de dados PostgreSQL (Supabase)
├── requirements.txt # Dependências do projeto
├── README.md # Este ficheiro

markdown
Copiar
Editar

---

## 🚀 Funcionalidades

- **Dashboard**
  - Estatísticas gerais
  - Últimas cotações
- **Nova Cotação**
  - Criar RFQs com múltiplos artigos
  - Associar fornecedor e marca
  - Gerar PDF de pedido
- **Responder Cotações**
  - Inserir preços, prazos e dados logísticos
  - Cálculo automático de preços de venda baseado na margem
  - Geração e envio automático de PDF para o cliente
- **Relatórios**
  - Estatísticas gerais e por fornecedor
- **Gestão de PDFs**
  - Todos os utilizadores podem visualizar
  - Apenas administradores podem substituir os ficheiros
- **Layout de PDF personalizável**
  - Ajuste textos, fontes e posicionamentos através de `Configurações > Layout PDF`
- **Configurações**
  - Gestão de fornecedores, marcas e margens
  - Configuração de e-mail para envio automático
  - Backup da base de dados
  - Agendamento de backup diário automático

---

## 🛠️ Instalação

1. **Clonar o repositório**
```bash
git clone https://github.com/teu-utilizador/erp-ktb.git
cd erp-ktb
Criar ambiente virtual (opcional, mas recomendado)

bash
Copiar
Editar
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
Instalar dependências

bash
Copiar
Editar
pip install -r requirements.txt
Criar/Inicializar base de dados

bash
Copiar
Editar
python db.py
▶️ Executar a aplicação
bash
Copiar
Editar
streamlit run main.py
A aplicação abrirá no navegador padrão, normalmente em:

arduino
Copiar
Editar
http://localhost:8501
📦 Dependências principais
streamlit – Interface web interativa

PostgreSQL (via Supabase) – Base de dados externa

fpdf – Geração de PDFs

smtplib – Envio de emails

Antes de executar a aplicação, defina a variável de ambiente `DATABASE_URL` com a sua string de ligação Supabase, por exemplo:

```bash
export DATABASE_URL="postgresql://postgres.metfqkdducobgjkjrris:MkA2w%2FE%21G3ErJUu@aws-1-eu-west-3.pooler.supabase.com:5432/postgres"
```

Instalação manual:

bash
Copiar
Editar
pip install streamlit fpdf

### 📝 Personalização de Layout dos PDFs

O layout dos PDFs de pedido e cliente é definido em `pdf_layout.json` e pode ser
ajustado diretamente pela aplicação em **Configurações > Layout PDF**.
Altere textos, tamanhos de letra, cabeçalhos ou posições e as mudanças são
aplicadas imediatamente.
📌 Notas
A base de dados é externa (Supabase), pelo que não é criado ficheiro local.

As configurações de e-mail devem ser definidas em EMAIL_CONFIG no main.py ou diretamente na interface em "Configurações > Email".

Para envio de e-mails via Gmail, é necessário gerar uma palavra-passe de aplicação na conta Google.

### ⏰ Backup automático diário

Executa o agendador para criar uma cópia diária da base de dados:

```bash
python backup_scheduler.py
```

Os ficheiros de backup são guardados na pasta `backups/` com a data no nome.

📜 Licença
Projeto interno da KTB Portugal – uso restrito.

yaml
Copiar
Editar

---

Se quiseres, eu posso complementar este README com a **explicação de cada função do `db.py`** para facilitar manutenção futura.  
Queres que o README já inclua isso?
