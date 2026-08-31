"""
CalDAV MCP Connector
=====================
Connettore MCP (stdio) che espone un server CalDAV (Nextcloud, Synology
Calendar, iCloud, Fastmail, Radicale, ecc.) a Claude Desktop.

Configurazione via variabili d'ambiente (vedi README.md):
    CALDAV_URL       -> URL principale del server CalDAV
    CALDAV_USERNAME  -> username
    CALDAV_PASSWORD  -> password o app-password
    CALDAV_CALENDAR  -> (opzionale) nome calendario di default

Tool esposti:
    - list_calendars
    - list_events
    - search_events
    - get_event
    - create_event
    - update_event
    - delete_event
"""

import os
import sys
import uuid
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional

import caldav
from caldav.elements import dav
from dotenv import load_dotenv
from icalendar import Calendar as ICalendar, Event as IEvent, Todo as ITodo
import recurring_ical_events

from mcp.server.fastmcp import FastMCP

# Carica le variabili d'ambiente dal file .env nella directory del server (o via CALDAV_ENV_FILE)
_env_path = os.environ.get("CALDAV_ENV_FILE") or (Path(__file__).resolve().parent / ".env")
load_dotenv(dotenv_path=_env_path)

mcp = FastMCP("caldav-connector")

# --------------------------------------------------------------------------
# Client / connection handling
# --------------------------------------------------------------------------

_client_cache = None
_principal_cache = None


def _get_env(name: str, required: bool = True, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(
            f"Variabile d'ambiente mancante: {name}. "
            "Configurala nel file .env o nelle variabili d'ambiente dell'MCP host."
        )
    return value


def _get_client() -> caldav.DAVClient:
    global _client_cache
    if _client_cache is None:
        url = _get_env("CALDAV_URL")
        username = _get_env("CALDAV_USERNAME")
        password = _get_env("CALDAV_PASSWORD")
        _client_cache = caldav.DAVClient(url=url, username=username, password=password)
    return _client_cache


def _get_principal():
    global _principal_cache
    if _principal_cache is None:
        _principal_cache = _get_client().principal()
    return _principal_cache


def _cal_name(cal) -> str:
    """Nome visualizzato di una collezione CalDAV. Usa get_display_name()
    (l'attributo .name è deprecato nella libreria caldav) con una cache
    locale sull'oggetto per evitare richieste ripetute al server."""
    cached = getattr(cal, "_display_name_cache", None)
    if cached:
        return cached
    try:
        name = cal.get_display_name()
    except Exception:
        name = None
    if not name:
        name = str(cal.url)
    cal._display_name_cache = name
    return name


def _supports(cal, component: str) -> bool:
    """True se la collezione CalDAV supporta il tipo di componente dato
    (VEVENT o VTODO). Se l'informazione non è disponibile, assume di sì
    (alcuni server, incluso Synology, non sempre la espongono correttamente)."""
    try:
        supported = cal.get_supported_components()
        if not supported:
            return True
        return component in supported
    except Exception:
        return True


def _find_calendar(calendar_name: Optional[str] = None, component: str = "VEVENT"):
    """Trova un calendario/lista per nome (case-insensitive, match parziale),
    filtrando per tipo di componente supportato (VEVENT per i calendari eventi,
    VTODO per le liste di promemoria). Se calendar_name è None usa
    CALDAV_CALENDAR/CALDAV_TODO_LIST o la prima collezione compatibile disponibile."""
    calendars = _get_principal().calendars()
    if not calendars:
        raise RuntimeError("Nessun calendario trovato per questo account.")

    candidates = [c for c in calendars if _supports(c, component)] or calendars

    env_var = "CALDAV_TODO_LIST" if component == "VTODO" else "CALDAV_CALENDAR"
    target = calendar_name or os.environ.get(env_var)
    if not target:
        return candidates[0]

    target_lower = target.lower().strip()
    for cal in candidates:
        if _cal_name(cal).lower() == target_lower:
            return cal
    for cal in candidates:
        if target_lower in _cal_name(cal).lower():
            return cal

    names = ", ".join(_cal_name(c) for c in candidates)
    kind = "lista di promemoria" if component == "VTODO" else "calendario"
    raise RuntimeError(f"{kind.capitalize()} '{calendar_name}' non trovato. Disponibili: {names}")


def _parse_date(value: str) -> datetime:
    """Accetta 'YYYY-MM-DD' o 'YYYY-MM-DDTHH:MM:SS'."""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise RuntimeError(f"Formato data non valido: '{value}'. Usa YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS.")


def _fmt_dt(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    if isinstance(dt, date):
        return dt.isoformat()
    return str(dt)


def _event_to_dict(component, calendar_name: str) -> dict:
    return {
        "uid": str(component.get("UID", "")),
        "summary": str(component.get("SUMMARY", "")),
        "description": str(component.get("DESCRIPTION", "")) if component.get("DESCRIPTION") else "",
        "location": str(component.get("LOCATION", "")) if component.get("LOCATION") else "",
        "start": _fmt_dt(component.get("DTSTART").dt if component.get("DTSTART") else None),
        "end": _fmt_dt(component.get("DTEND").dt if component.get("DTEND") else None),
        "calendar": calendar_name,
    }


def _todo_to_dict(component, list_name: str) -> dict:
    status = str(component.get("STATUS", "NEEDS-ACTION"))
    priority = component.get("PRIORITY")
    return {
        "uid": str(component.get("UID", "")),
        "summary": str(component.get("SUMMARY", "")),
        "description": str(component.get("DESCRIPTION", "")) if component.get("DESCRIPTION") else "",
        "due": _fmt_dt(component.get("DUE").dt if component.get("DUE") else None),
        "status": status,
        "completed": status == "COMPLETED",
        "priority": int(priority) if priority is not None else None,
        "list": list_name,
    }


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

@mcp.tool()
def list_calendars() -> list[dict]:
    """Elenca tutte le collezioni CalDAV disponibili (sia calendari eventi che
    liste di promemoria/VTODO), indicando per ognuna cosa supporta."""
    calendars = _get_principal().calendars()
    result = []
    for cal in calendars:
        supports_events = _supports(cal, "VEVENT")
        supports_todos = _supports(cal, "VTODO")
        result.append({
            "name": _cal_name(cal),
            "url": str(cal.url),
            "type": "eventi" if supports_events and not supports_todos
                    else "promemoria" if supports_todos and not supports_events
                    else "eventi+promemoria",
        })
    return result


@mcp.tool()
def list_events(
    calendar_name: Optional[str] = None,
    days_ahead: int = 7,
    days_back: int = 0,
    include_recurring: bool = True,
) -> list[dict]:
    """Elenca gli eventi in una finestra temporale relativa a oggi.

    Args:
        calendar_name: nome del calendario (default: il calendario di default configurato o il primo disponibile).
        days_ahead: quanti giorni nel futuro includere (default 7).
        days_back: quanti giorni nel passato includere (default 0).
        include_recurring: se True, espande le ricorrenze (es. eventi settimanali) nella finestra.
    """
    cal = _find_calendar(calendar_name)
    start = datetime.now() - timedelta(days=days_back)
    end = datetime.now() + timedelta(days=days_ahead)

    events_out = []

    if include_recurring:
        for cal_event in cal.date_search(start=start, end=end, expand=True):
            ical = ICalendar.from_ical(cal_event.data)
            for component in ical.walk("VEVENT"):
                events_out.append(_event_to_dict(component, _cal_name(cal)))
    else:
        for cal_event in cal.date_search(start=start, end=end, expand=False):
            ical = ICalendar.from_ical(cal_event.data)
            for component in ical.walk("VEVENT"):
                events_out.append(_event_to_dict(component, _cal_name(cal)))

    events_out.sort(key=lambda e: e["start"] or "")
    return events_out


@mcp.tool()
def search_events(query: str, calendar_name: Optional[str] = None, days_ahead: int = 365) -> list[dict]:
    """Cerca eventi il cui titolo, descrizione o luogo contiene la stringa data.

    Args:
        query: testo da cercare (case-insensitive).
        calendar_name: se omesso cerca in tutti i calendari.
        days_ahead: finestra futura di ricerca in giorni (default 365).
    """
    query_lower = query.lower()
    calendars = [_find_calendar(calendar_name)] if calendar_name else _get_principal().calendars()

    start = datetime.now() - timedelta(days=30)
    end = datetime.now() + timedelta(days=days_ahead)

    matches = []
    for cal in calendars:
        try:
            for cal_event in cal.date_search(start=start, end=end, expand=True):
                ical = ICalendar.from_ical(cal_event.data)
                for component in ical.walk("VEVENT"):
                    haystack = " ".join(
                        str(component.get(f, "")) for f in ("SUMMARY", "DESCRIPTION", "LOCATION")
                    ).lower()
                    if query_lower in haystack:
                        matches.append(_event_to_dict(component, _cal_name(cal)))
        except Exception:
            continue

    matches.sort(key=lambda e: e["start"] or "")
    return matches


@mcp.tool()
def get_event(uid: str, calendar_name: Optional[str] = None) -> dict:
    """Recupera un singolo evento tramite il suo UID."""
    cal = _find_calendar(calendar_name)
    cal_event = cal.event_by_uid(uid)
    ical = ICalendar.from_ical(cal_event.data)
    for component in ical.walk("VEVENT"):
        return _event_to_dict(component, _cal_name(cal))
    raise RuntimeError(f"Evento con UID {uid} non trovato.")


@mcp.tool()
def create_event(
    summary: str,
    start: str,
    end: str,
    calendar_name: Optional[str] = None,
    description: str = "",
    location: str = "",
) -> dict:
    """Crea un nuovo evento nel calendario.

    Args:
        summary: titolo dell'evento.
        start: data/ora inizio, formato YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS.
        end: data/ora fine, stesso formato.
        calendar_name: calendario di destinazione (default: quello configurato/primo).
        description: descrizione opzionale.
        location: luogo opzionale.
    """
    cal = _find_calendar(calendar_name)
    dtstart = _parse_date(start)
    dtend = _parse_date(end)
    event_uid = str(uuid.uuid4())

    ical = ICalendar()
    ical.add("prodid", "-//caldav-mcp-connector//IT")
    ical.add("version", "2.0")

    vevent = IEvent()
    vevent.add("uid", event_uid)
    vevent.add("summary", summary)
    vevent.add("dtstart", dtstart)
    vevent.add("dtend", dtend)
    vevent.add("dtstamp", datetime.now())
    if description:
        vevent.add("description", description)
    if location:
        vevent.add("location", location)

    ical.add_component(vevent)
    cal.save_event(ical.to_ical().decode("utf-8"))

    return {"uid": event_uid, "summary": summary, "start": start, "end": end, "calendar": _cal_name(cal)}


@mcp.tool()
def update_event(
    uid: str,
    calendar_name: Optional[str] = None,
    summary: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
) -> dict:
    """Aggiorna i campi indicati di un evento esistente (identificato da UID).
    Solo i campi passati vengono modificati."""
    cal = _find_calendar(calendar_name)
    cal_event = cal.event_by_uid(uid)
    ical = ICalendar.from_ical(cal_event.data)

    for component in ical.walk("VEVENT"):
        if summary is not None:
            component["SUMMARY"] = summary
        if description is not None:
            component["DESCRIPTION"] = description
        if location is not None:
            component["LOCATION"] = location
        if start is not None:
            component["DTSTART"].dt = _parse_date(start)
        if end is not None:
            component["DTEND"].dt = _parse_date(end)

    cal_event.data = ical.to_ical().decode("utf-8")
    cal_event.save()

    for component in ical.walk("VEVENT"):
        return _event_to_dict(component, _cal_name(cal))


@mcp.tool()
def delete_event(uid: str, calendar_name: Optional[str] = None) -> dict:
    """Elimina un evento identificato dal suo UID."""
    cal = _find_calendar(calendar_name)
    cal_event = cal.event_by_uid(uid)
    cal_event.delete()
    return {"deleted_uid": uid, "calendar": _cal_name(cal)}


@mcp.tool()
def list_todo_lists() -> list[dict]:
    """Elenca solo le collezioni che supportano i promemoria/task (VTODO)."""
    calendars = _get_principal().calendars()
    result = []
    for cal in calendars:
        if _supports(cal, "VTODO"):
            try:
                count = len(cal.todos(include_completed=True))
            except Exception:
                count = None
        else:
            continue
        result.append({"name": _cal_name(cal), "url": str(cal.url), "todos_count": count})
    return result


@mcp.tool()
def list_todos(list_name: Optional[str] = None, include_completed: bool = False) -> list[dict]:
    """Elenca i promemoria/task di una lista VTODO, ordinati per scadenza e priorità.

    Args:
        list_name: nome della lista promemoria (default: quella configurata o la prima compatibile).
        include_completed: se True include anche i promemoria già completati.
    """
    todo_list = _find_calendar(list_name, component="VTODO")
    todos = todo_list.todos(include_completed=include_completed)
    result = []
    for todo_obj in todos:
        ical = ICalendar.from_ical(todo_obj.data)
        for component in ical.walk("VTODO"):
            result.append(_todo_to_dict(component, _cal_name(todo_list)))
    return result


@mcp.tool()
def create_todo(
    summary: str,
    list_name: Optional[str] = None,
    due: Optional[str] = None,
    description: str = "",
    priority: Optional[int] = None,
) -> dict:
    """Crea un nuovo promemoria/task in una lista VTODO.

    Args:
        summary: titolo del promemoria.
        list_name: lista di destinazione (default: quella configurata o la prima compatibile).
        due: scadenza opzionale, formato YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS.
        description: descrizione opzionale.
        priority: priorità opzionale 1 (alta) - 9 (bassa), standard iCalendar.
    """
    todo_list = _find_calendar(list_name, component="VTODO")
    todo_uid = str(uuid.uuid4())

    ical = ICalendar()
    ical.add("prodid", "-//caldav-mcp-connector//IT")
    ical.add("version", "2.0")

    vtodo = ITodo()
    vtodo.add("uid", todo_uid)
    vtodo.add("summary", summary)
    vtodo.add("dtstamp", datetime.now())
    vtodo.add("status", "NEEDS-ACTION")
    if due:
        vtodo.add("due", _parse_date(due))
    if description:
        vtodo.add("description", description)
    if priority is not None:
        vtodo.add("priority", priority)

    ical.add_component(vtodo)
    todo_list.save_todo(ical.to_ical().decode("utf-8"))

    return {"uid": todo_uid, "summary": summary, "due": due, "list": _cal_name(todo_list)}


@mcp.tool()
def update_todo(
    uid: str,
    list_name: Optional[str] = None,
    summary: Optional[str] = None,
    due: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[int] = None,
) -> dict:
    """Aggiorna i campi indicati di un promemoria esistente (identificato da UID).
    Solo i campi passati vengono modificati."""
    todo_list = _find_calendar(list_name, component="VTODO")
    todo_obj = todo_list.todo_by_uid(uid)
    ical = ICalendar.from_ical(todo_obj.data)

    for component in ical.walk("VTODO"):
        if summary is not None:
            component["SUMMARY"] = summary
        if description is not None:
            component["DESCRIPTION"] = description
        if priority is not None:
            component["PRIORITY"] = priority
        if due is not None:
            component["DUE"] = _parse_date(due)

    todo_obj.data = ical.to_ical().decode("utf-8")
    todo_obj.save()

    for component in ical.walk("VTODO"):
        return _todo_to_dict(component, _cal_name(todo_list))


@mcp.tool()
def complete_todo(uid: str, list_name: Optional[str] = None) -> dict:
    """Segna un promemoria come completato (STATUS=COMPLETED)."""
    todo_list = _find_calendar(list_name, component="VTODO")
    todo_obj = todo_list.todo_by_uid(uid)
    ical = ICalendar.from_ical(todo_obj.data)

    for component in ical.walk("VTODO"):
        component["STATUS"] = "COMPLETED"
        component["COMPLETED"] = datetime.now()

    todo_obj.data = ical.to_ical().decode("utf-8")
    todo_obj.save()

    for component in ical.walk("VTODO"):
        return _todo_to_dict(component, _cal_name(todo_list))


@mcp.tool()
def delete_todo(uid: str, list_name: Optional[str] = None) -> dict:
    """Elimina definitivamente un promemoria identificato dal suo UID."""
    todo_list = _find_calendar(list_name, component="VTODO")
    todo_obj = todo_list.todo_by_uid(uid)
    todo_obj.delete()
    return {"deleted_uid": uid, "list": _cal_name(todo_list)}


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
