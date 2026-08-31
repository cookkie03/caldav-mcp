# CalDAV MCP Connector

Connettore MCP (Model Context Protocol) che collega Claude Desktop (o qualsiasi client compatibile MCP) a **qualsiasi server CalDAV**: Nextcloud, Synology Calendar/CardDAV, iCloud, Fastmail, Radicale, Google Calendar (via bridge CalDAV), ecc.

Espone 13 tool all'assistente AI:
- **Eventi**: `list_calendars`, `list_events`, `search_events`, `get_event`, `create_event`, `update_event`, `delete_event`
- **Promemoria/task (VTODO)**: `list_todo_lists`, `list_todos`, `create_todo`, `update_todo`, `complete_todo`, `delete_todo`

---

## 1. Installazione (una volta sola)

Serve Python 3.10+ già installato sul tuo Mac/PC.

```bash
# 1. Clona o estrai i file in una cartella fissa, es. ~/mcp-servers/caldav-mcp/
git clone https://github.com/cookkie03/caldav-mcp.git
cd caldav-mcp

# 2. Crea un virtualenv dedicato
python3 -m venv .venv
source .venv/bin/activate      # su Windows: .venv\Scripts\activate

# 3. Installa le dipendenze
pip install -r requirements.txt
```

---

## 2. Configurazione delle variabili d'ambiente (`.env`)

Il server carica automaticamente le configurazioni e credenziali da un file `.env` presente nella cartella del progetto.

1. Copia il template `.env.example`:
   ```bash
   cp .env.example .env
   ```
2. Modifica `.env` con i parametri del tuo server:
   ```env
   CALDAV_URL=https://TUO_NAS:5001/caldav/
   CALDAV_USERNAME=tuo-username
   CALDAV_PASSWORD=la-tua-password

   # Opzionali (nomi di fallback se non specificati nei prompt)
   CALDAV_CALENDAR=Personale
   CALDAV_TODO_LIST=Promemoria
   ```

### Parametri tipici per i vari servizi:

| Servizio | CALDAV_URL | Note |
|---|---|---|
| Synology Calendar | `https://TUO_NAS:5001/caldav/` | Attiva CalDAV in Pacchetto Calendar → Impostazioni. Usa l'URL DDNS con certificato SSL valido se presente |
| Nextcloud | `https://TUO_DOMINIO/remote.php/dav/` | Crea una **app password** in Impostazioni → Sicurezza |
| iCloud | `https://caldav.icloud.com/` | Richiede una **app-specific password** generata da appleid.apple.com |
| Fastmail | `https://caldav.fastmail.com/dav/` | Usa un'app password dedicata |
| Radicale | `http://host:5232/USERNAME/` | In base alla configurazione del demone |

---

## 3. Configura il Client MCP (es. Claude Desktop)

Apri il file di configurazione del client MCP:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Aggiungi la voce dentro `"mcpServers"`. Poiché le credenziali sono salvate nel `.env`, la configurazione rimane minimale e sicura:

```json
{
  "mcpServers": {
    "caldav": {
      "command": "/PERCORSO/ASSOLUTO/caldav-mcp/.venv/bin/python3",
      "args": ["/PERCORSO/ASSOLUTO/caldav-mcp/server.py"]
    }
  }
}
```

> **Nota per macOS/Linux**: Sostituisci `/PERCORSO/ASSOLUTO/` con il path reale (es. `/Users/nome/mcp-servers/caldav-mcp`).  
> **Nota percorso personalizzato**: Se desideri posizionare il file `.env` altrove, puoi specificare la variabile `CALDAV_ENV_FILE` nel blocco `"env"` del JSON indicando il percorso assoluto del file.

Riavvia Claude Desktop: nei connettori MCP attivi comparirà `caldav` con tutti i tool disponibili.

---

## 4. Esempi d'uso in chat

- *"Che impegni ho questa settimana?"*
- *"Crea un evento 'Palestra' domani dalle 18:00 alle 19:00"*
- *"Cerca tutti gli eventi che parlano di 'dentista'"*
- *"Sposta l'evento riunione di venerdì alle 15:00"*
- *"Elenca tutti i miei calendari"*
- *"Aggiungi 'comprare il latte' ai promemoria"*
- *"Che promemoria ho ancora da completare?"*
- *"Segna come completato il promemoria 'chiamare il commercialista'"*

---

## 5. Struttura del progetto

```
caldav-mcp/
├── .env.example       # Template di configurazione variabili d'ambiente
├── .gitignore         # Ignora .env, .venv, cache Python
├── README.md          # Documentazione
├── requirements.txt   # Dipendenze Python
└── server.py          # Server MCP FastMCP
```

---

## 6. Note tecniche

- Espande automaticamente gli **eventi ricorrenti** (settimanali, mensili...) nella finestra temporale richiesta (`recurring-ical-events`).
- `search_events` cerca su titolo, descrizione e luogo, su uno o tutti i calendari.
- Ogni evento creato riceve uno **UID univoco** che puoi riusare per `update_event` / `delete_event`.
- `list_calendars(calendar_name=None)` supporta match case-insensitive e parziale.
- Distingue automaticamente le collezioni "eventi", "promemoria" e "eventi+promemoria" leggendo il `supported-calendar-component-set`.
- Nessun dato viene tracciato o loggato: ogni chiamata comunica direttamente col server CalDAV.
