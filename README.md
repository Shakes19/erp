# 📊 ERP KTB Portugal

Sistema de gestão de cotações desenvolvido em **Python** com **Streamlit** e **SQLite**, permitindo:
- Criar e gerir pedidos de cotação (RFQs)
- Responder cotações e enviar orçamentos
- Gerar PDFs automáticos (pedido e cliente)
- Configurar fornecedores, marcas e margens
- Enviar orçamentos por e-mail diretamente pelo sistema

---

## 📂 Estrutura do Projeto

.
├── main.py # Interface principal Streamlit e lógica de negócio
├── db.py # Funções de conexão e gestão da base de dados SQLite
├── requirements.txt # Dependências do projeto
├── cotacoes.db # Base de dados SQLite (gerada automaticamente)
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
- **Configurações**
  - Gestão de fornecedores, marcas e margens
  - Configuração de e-mail para envio automático
  - Backup da base de dados

---

## 🛠️ Instalação

1. **Clonar o repositório**
```bash
git clone https://github.com/teu-usuario/erp-ktb.git
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

sqlite3 – Base de dados local

fpdf – Geração de PDFs

smtplib – Envio de emails

Instalação manual:

bash
Copiar
Editar
pip install streamlit fpdf
📌 Notas
A base de dados (cotacoes.db) é criada automaticamente ao iniciar a aplicação se não existir.

As configurações de e-mail devem ser definidas em EMAIL_CONFIG no main.py ou diretamente na interface em "Configurações > Email".

Para envio de e-mails via Gmail, é necessário gerar senha de aplicação na conta Google.

📜 Licença
Projeto interno da KTB Portugal – uso restrito.

yaml
Copiar
Editar

---

Se quiseres, eu posso complementar este README com a **explicação de cada função do `db.py`** para facilitar manutenção futura.  
Queres que o README já inclua isso?
