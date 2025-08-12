import os
import time
from datetime import datetime

import schedule

from db import backup_database

BACKUP_DIR = "backups"


def _daily_backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d")
    backup_path = os.path.join(BACKUP_DIR, f"cotacoes_{timestamp}.db")
    backup_database(backup_path)


def agendar_backup_diario(hora="00:00"):
    """Agenda um backup diário da base de dados para a hora especificada."""
    schedule.every().day.at(hora).do(_daily_backup)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    agendar_backup_diario()
