# config.py
import os
from urllib.parse import urlparse

# Configuração da base de dados Supabase
DATABASE_URL = "postgresql://postgres.metfqkdducobgjkjrris:MkA2w/E!G3ErJUu@aws-1-eu-west-3.pooler.supabase.com:5432/postgres"

# Parse da URL para obter componentes individuais
url = urlparse(DATABASE_URL)

DB_CONFIG = {
    'host': url.hostname,
    'port': url.port or 5432,
    'database': url.path[1:],  # Remove a barra inicial
    'user': url.username,
    'password': url.password,
    'sslmode': 'require'  # Necessário para Supabase
}

# Configurações de Email (mantidas do sistema original)
EMAIL_CONFIG = {
    'smtp_server': 'smtp-mail.outlook.com',
    'smtp_port': 587
}

# Configurações gerais
BACKUP_DIR = "backups"
