# CalDAV MCP Connector

Connettore MCP (Model Context Protocol) che collega Claude Desktop a **qualsiasi
server CalDAV**: Nextcloud, Synology Calendar/CardDAV, iCloud, Fastmail,
Radicale, Google Calendar (via bridge CalDAV), ecc.

Espone 13 tool a Claude:
- **Eventi**: `list_calendars`, `list_events`, `search_events`, `get_event`, `create_event`, `update_event`, `delete_event`
- **Promemoria/task (VTODO)**: `list_todo_lists`, `list_todos`, `create_todo`, `update_todo`, `complete_todo`, `delete_todo`

---

## 1. Installazione (una volta sola)

Serve Python 3.10+ già installato sul tuo Mac/PC.

```bash
# 1. Estrai i file in una cartella fissa, es. ~/mcp-servers/caldav-mcp/
cd ~/mcp-servers/caldav-mcp/

# 2. Crea un virtualenv dedicato (consigliato, evita conflitti di pacchetti)
python3 -m venv .venv
source .venv/bin/activate      # su Windows: .venv\Scripts\activate

# 3. Installa le dipendenze (versioni testate e fissate)
pip install -r requirements.txt
```

Verifica rapida che tutto sia a posto:

```bash
python3 -c "from mcp.server.fastmcp import FastMCP; print('OK')"
```

## 2. Trova i parametri del tuo server CalDAV

| Servizio | CALDAV_URL | Note |
|---|---|---|
| Nextcloud | `https://TUO_DOMINIO/remote.php/dav/` | crea un **app password** dedicato in Impostazioni → Sicurezza, non usare la password principale |
| Synology Calendar | `https://TUO_NAS:5001/caldav/` | attiva CalDAV in Pacchetto Calendar → Impostazioni |
| iCloud | `https://caldav.icloud.com/` | serve una **app-specific password** da appleid.apple.com |
| Fastmail | `https://caldav.fastmail.com/dav/` | app password dedicato |
| Radicale | dipende dal tuo setup | di solito `http://host:5232/USERNAME/` |

Per il tuo caso — **Synology Calendar** con liste eventi e liste di
promemoria (VTODO) — usa:

```
CALDAV_URL=https://TUO_NAS:5001/caldav/
```

Attiva CalDAV in **Pacchetto Calendar → Impostazioni → CalDAV**, e usa le tue
credenziali DSM (o un account dedicato se preferisci non usare l'admin).
Se il NAS ha un certificato self-signed potresti dover importare il
certificato o usare l'URL DDNS con certificato valido (hai già
`lucamanca.synology.me` configurato, quindi puoi probabilmente usare
`https://lucamanca.synology.me:5001/caldav/`).

Synology espone sia i calendari eventi che le liste di promemoria come
collezioni CalDAV nello stesso account: il connettore le distingue da solo
(vedi sezione 6) e i tool `list_todo_lists` / `list_todos` /
`create_todo` / `update_todo` / `complete_todo` / `delete_todo` lavorano
solo sulle liste di tipo VTODO.

## 3. Configura Claude Desktop

Apri il file di configurazione:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Aggiungi (o unisci) questa voce dentro `"mcpServers"`:

```json
{
  "mcpServers": {
    "caldav": {
      "command": "/PERCORSO/ASSOLUTO/caldav-mcp/.venv/bin/python3",
      "args": ["/PERCORSO/ASSOLUTO/caldav-mcp/server.py"],
      "env": {
        "CALDAV_URL": "https://lucamanca.synology.me:5001/caldav/",
        "CALDAV_USERNAME": "tuo-username-dsm",
        "CALDAV_PASSWORD": "la-tua-password",
        "CALDAV_CALENDAR": "Personale",
        "CALDAV_TODO_LIST": "Promemoria"
      }
    }
  }
}
```

Note:
- `command` deve puntare al Python **dentro il virtualenv** (`.venv/bin/python3`
  su Mac/Linux, `.venv\Scripts\python.exe` su Windows), non al Python di sistema.
- `CALDAV_CALENDAR` e `CALDAV_TODO_LIST` sono opzionali: sono rispettivamente
  il calendario eventi e la lista promemoria usati di default se non
  specifichi un nome nella richiesta. Se li ometti, il connettore usa la
  prima collezione compatibile disponibile.
- Non serve mai passare in chiaro dati sensibili a Claude: le credenziali
  restano nel file di config locale, letto solo dal processo del connettore.

Riavvia Claude Desktop. Nella lista dei connettori/MCP dovresti vedere
"caldav" con i 7 tool disponibili.

## 4. Esempi d'uso in chat

- "Che impegni ho questa settimana?"
- "Crea un evento 'Palestra' domani dalle 18:00 alle 19:00"
- "Cerca tutti gli eventi che parlano di 'dentista'"
- "Sposta l'evento riunione di venerdì alle 15:00"
- "Elenca tutti i miei calendari"
- "Aggiungi 'comprare il latte' ai promemoria"
- "Che promemoria ho ancora da completare?"
- "Segna come completato il promemoria 'chiamare il commercialista'"

## 5. Struttura del progetto

```
caldav-mcp/
├── server.py          # il connettore MCP (unico file necessario a runtime)
├── requirements.txt   # dipendenze pinnate
└── README.md
```

## 6. Note tecniche / potenza del connettore

- Espande automaticamente gli **eventi ricorrenti** (settimanali, mensili...)
  nella finestra temporale richiesta, grazie a `recurring-ical-events`.
- `search_events` cerca su titolo, descrizione e luogo, su uno o tutti i
  calendari.
- Ogni evento creato riceve uno **UID univoco** che puoi riusare per
  `update_event` / `delete_event` — Claude te lo restituisce dopo la
  creazione, così può referenziarlo nella stessa conversazione.
- `list_calendars(calendar_name=None)` fa match case-insensitive anche
  parziale sul nome, quindi puoi dire "aggiungilo al calendario lavoro"
  anche se il nome esatto è "Lavoro - Team".
- Nessun dato viene salvato o loggato dal connettore: ogni chiamata parla
  direttamente col tuo server CalDAV via HTTPS.
- `list_calendars` distingue automaticamente le collezioni "eventi",
  "promemoria" e "eventi+promemoria" leggendo il `supported-calendar-component-set`
  esposto dal server (Synology lo espone correttamente).

## 7. Estenderlo

Il file `server.py` è volutamente compatto e leggibile: per aggiungere un
tool nuovo basta scrivere una funzione Python e decorarla con `@mcp.tool()`,
seguendo lo stile degli altri tool già presenti.
