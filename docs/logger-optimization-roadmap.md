# Claude Code Logger - Optimization Implementation Roadmap

**Status:** Analysis Complete | Ready for Phase 1 Implementation  
**Version:** 2.0.0 (Planned)  
**Last Updated:** 2025-11-06  
**Analyst:** Claude (Sequential Thinking + Context7 + WebSearch)

---

## Executive Summary

Umfassende Analyse aller 7 Optimierungsvorschläge aus [claude-code-logger-analyse.md](./claude-code-logger-analyse.md):

| # | Optimierung | Status | Aufwand | Impact | Phase |
|---|---|---|---|---|---|
| 8.1 | Schema-Felder ergänzen | ✅ Akzeptiert | 10min | HIGH | 1 |
| 8.2 | Background-Task-Tracking | ✅ Akzeptiert | 1-2h | MEDIUM | 3 |
| 8.3 | Strukturierte Meta-Daten | ✅ Akzeptiert (vereinfacht) | 5min | MEDIUM | 1 |
| 8.4 | In-Memory-Caching | ❌ Abgelehnt | - | - | - |
| 8.5 | Tool-Normalisierung Registry | ✅ Akzeptiert | 3-4h | MEDIUM | 3 |
| 8.6 | Async-Logging | ❌ Abgelehnt | - | - | - |
| 8.7 | Compression & Rotation | ✅ Akzeptiert | 2-3h | HIGH | 2 |

**Gesamt-Umsetzung:** ~6-8 Stunden über 3 Phasen

---

## Validierungsergebnisse

### ✅ Akzeptierte Optimierungen (5/7)

#### 8.1 Fehlende Schema-Felder ergänzen
**Status:** VALIDIERT ✅  
**Code-Zeilen:** 615-622

**Problem:**
```python
# AKTUELL (Zeile 615-622):
elif event_name == "SessionStart":
    base.update({"phase": "start", "cwd": safe_get(hook_input, "cwd", default="")})
# FEHLT: source, transcript_path, permission_mode

elif event_name == "SessionEnd":
    base.update({"phase": "end", "reason": safe_get(hook_input, "reason", default="")})
# FEHLT: transcript_path, cwd (!)

elif event_name == "PreCompact":
    base.update({"phase": "compact"})
# FEHLT: trigger, custom_instructions
```

**Lösung:**
```python
elif event_name == "SessionStart":
    base.update({
        "phase": "start",
        "cwd": safe_get(hook_input, "cwd", default=""),
        "source": safe_get(hook_input, "source", default=""),  # ✅ NEU
        "transcript_path": safe_get(hook_input, "transcript_path", default=""),  # ✅ NEU
        "permission_mode": safe_get(hook_input, "permission_mode", default="")  # ✅ NEU
    })

elif event_name == "SessionEnd":
    base.update({
        "phase": "end",
        "reason": safe_get(hook_input, "reason", default=""),
        "cwd": safe_get(hook_input, "cwd", default=""),  # ✅ NEU
        "transcript_path": safe_get(hook_input, "transcript_path", default="")  # ✅ NEU
    })

elif event_name == "PreCompact":
    base.update({
        "phase": "compact",
        "trigger": safe_get(hook_input, "trigger", default=""),  # ✅ NEU
        "custom_instructions": safe_get(hook_input, "custom_instructions", default="")  # ✅ NEU
    })
```

**Nutzen:**
- ✅ Vollständige Hook-Input-Schema Abdeckung
- ✅ Session-Lifecycle Tracking Verbesserung
- ✅ Permission-Mode für Compliance-Audits
- ✅ Transcript-Path für Post-Processing

**Komplexität:** LOW (einfache safe_get() Aufrufe)

---

#### 8.3 Strukturierte Meta-Daten für Observability
**Status:** VALIDIERT (vereinfacht) ✅

**Original-Vorschlag:** Zu komplex (würde Cache-Reads pro Event erfordern)

**Vereinfachte Lösung:** Logger-Versionierung

```python
# Top of file (Zeile 19-20):
LOG_VERSION = "2.0.0"  # ✅ NEU

# In extract_event_data() (alle Events):
base["version"] = LOG_VERSION
```

**Nutzen:**
- ✅ Breaking-Change-Tracking
- ✅ Log-Format-Versionierung
- ✅ Migration-Guide Ermöglichung
- ✅ Abwärts-Kompatibilität

**Komplexität:** MINIMAL (1 Konstante + 1 Zeile Code)

---

#### 8.7 Compression & Rotation
**Status:** VALIDIERT ✅  
**Code-Zeilen:** 658-668 (write_log_line)

**Problem:** Logs wachsen unbegrenzt → Disk-Full möglich

**Lösung:** Dateigröße-basierte Rotation
```python
# Neue Konstante:
LOG_MAX_SIZE_MB = int(os.getenv("CC_LOG_MAX_SIZE_MB", "100"))

# In write_log_line() (Zeile 658):
def rotate_logs_if_needed() -> None:
    try:
        if LOG_FILE.stat().st_size >= LOG_MAX_SIZE_MB * 1024 * 1024:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            rotated = LOG_FILE.with_stem(f"{LOG_FILE.stem}.{timestamp}")
            LOG_FILE.rename(rotated)
            
            # Asynchron komprimieren (nicht blockierend):
            import threading
            threading.Thread(
                target=lambda: gzip_file(rotated),
                daemon=True
            ).start()
            LOG_FILE.touch()  # Neuer Log-File

def write_log_line(log_entry: Dict[str, Any]) -> None:
    try:
        ensure_log_dir()
        rotate_logs_if_needed()  # ✅ VOR dem Schreiben prüfen
        
        json_bytes = orjson.dumps(log_entry)
        with open(LOG_FILE, "ab") as f:
            f.write(json_bytes)
            f.write(b"\n")
            f.flush()
    except Exception:
        pass
```

**Nutzen:**
- ✅ Bounded Log-Size (keine Disk-Full)
- ✅ Historische Logs komprimiert archivieren
- ✅ Automatisches Cleanup möglich
- ✅ Produktionsrelevanz (Must-Have)

**Komplexität:** MEDIUM (Threading, File-Ops)

---

#### 8.2 Background-Task-Completion-Tracking
**Status:** AKZEPTIERT (mit Validierungsbedingung) ✅

**Abhängigkeit:** Muss nach Schema-Validierung (8.1) erfolgen

**Problem:** bg_task_id existiert nur in PostToolUse, keine Start-Zeit-Korrelation

**Lösung:** 4. Cache-Datei für Background-Tasks

```python
# Neue Konstante:
BG_TASK_CACHE = LOG_FILE.parent / "background_tasks.json"

# In PostToolUse Handler (Zeile 548):
if bg_task_id := safe_get(hook_input, "background_task_id"):
    base["bg_task_id"] = bg_task_id
    
    # ✅ NEU: Background-Task Status cachen
    bg_cache = _load_cache(BG_TASK_CACHE)
    bg_cache[bg_task_id] = {
        "session_id": session_id_original,
        "tool_name": tool_name,
        "end_time": time.time(),
        "status": output.get("status", "unknown"),
        "duration_ms": base.get("duration_ms")
    }
    _save_cache(BG_TASK_CACHE, bg_cache)
```

**Nutzen:**
- ✅ Background-Task Lifetime-Analyse
- ✅ Parallel-Execution-Metrics
- ✅ Async-Debugging verbessert

**Komplexität:** MEDIUM (neue Cache-Struktur)

---

#### 8.5 Erweiterte Tool-Normalisierung
**Status:** AKZEPTIERT (als Refactoring Phase 3) ✅

**Problem:** normalize_tool_output() hat 100+ Zeilen if/elif Kette

**Lösung:** Tool-Normalizer Registry Pattern

```python
# Nach SECRET_PATTERNS (Zeile 44):
TOOL_NORMALIZERS = {
    "Bash": normalize_bash,
    "Read": normalize_file_op,
    "Write": normalize_file_op,
    "Edit": normalize_file_op,
    "Glob": normalize_file_op,
    "Grep": normalize_file_op,
    "WebSearch": normalize_websearch,
    "Task": normalize_task,
    "mcp__": normalize_mcp,
    # ✅ NEU: Einfach neue Normalizer hinzufügen
}

# Refactored normalize_tool_output():
def normalize_tool_output(tool_name: str, tool_response: Dict[str, Any],
                         tool_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized = {"status": "success", "data": None, "error": None, "meta": {}}
    
    # Finde passenden Normalizer:
    normalizer = None
    for pattern, norm_func in TOOL_NORMALIZERS.items():
        if pattern == "mcp__" and tool_name.startswith("mcp__"):
            normalizer = norm_func
            break
        elif tool_name == pattern:
            normalizer = norm_func
            break
    
    if normalizer:
        normalized = normalizer(tool_response, tool_input, normalized)
    else:
        # Fallback für unbekannte Tools
        normalized["status"] = tool_response.get("success", True)
        normalized["data"] = truncate(tool_response.get("data", ""))
    
    return {k: v for k, v in normalized.items() if v or k == "data"}
```

**Nutzen:**
- ✅ Erweiterbarkeit (keine Code-Änderungen nötig)
- ✅ Konsistente Tool-Output-Struktur
- ✅ Einfaches Hinzufügen neuer Tools
- ✅ Bessere Code-Organisation

**Komplexität:** MEDIUM (Refactoring-Effort)

---

### ❌ Abgelehnte Optimierungen (2/7)

#### 8.4 In-Memory-Caching mit CacheManager ❌
**Status:** ABGELEHNT (nicht anwendbar)

**Grund:**
```
Logger-Execution-Modell: CLI-Tool (short-lived process)

Probleme:
1. Jeder Hook-Call spawnt neuen Python-Process
2. In-Memory-State persistiert NICHT zwischen Calls
3. CacheManager.__init__() würde bei jedem Event neu laufen
4. _dirty-Set würde nie geflusht (Process endet sofort)

Resultat: Zero Nutzen, nur zusätzliche Komplexität
```

**Warum nicht anwendbar:**
```
Hook-Flow:
Hook-Event 1 → Python logger.py (Memory: {...}) → Exit → Speicher weg
Hook-Event 2 → Python logger.py (Memory: {...}) → Exit → Speicher weg
                                    ↑ Neuer Process, leerer Memory!
```

**Alternative:** Bestehende Disk-basierte Cache ist optimal

---

#### 8.6 Async-Logging für High-Throughput 💨 ❌
**Status:** ABGELEHNT (nicht anwendbar)

**Grund:**
```
Same Problem wie 8.4:

Original-Vorschlag: Threading + Queue
- Queue(maxsize=1000) 
- async_logger() Background-Thread

Probleme:
1. Background-Thread endet mit Process-Exit
2. Queue wird nicht geflusht
3. Neue Events = neue Processes = neue Queues
4. Threading macht keinen Sinn bei CLI-Invocation

Web-Search Insight:
"QueueHandler recommended für High-Frequency"
→ NUR anwendbar bei Long-Running Processes (Daemons)
→ Nicht bei stateless CLI-Tools
```

**Warum nicht nötig:**
- Aktuelle write_log_line() nutzt `.flush()` pro Event
- Disk-I/O minimal (orjson ist sehr schnell)
- Bei 100 Events/s: ~10-50ms pro Event (akzeptabel für Hook)

---

## Implementierungsplan

### Phase 1: Quick Wins (⏱️ ~30 Minuten)

**Ziel:** Basis-Verbesserungen + Versionierung

**Änderungen:**
1. ✅ Konstante: `LOG_VERSION = "2.0.0"` (Zeile 29)
2. ✅ SessionStart erweitern: +3 Felder (Zeile 615-620)
3. ✅ SessionEnd erweitern: +2 Felder (Zeile 618-623)
4. ✅ PreCompact erweitern: +2 Felder (Zeile 621-625)
5. ✅ FIELD_CONFIG erweitern: Neue Felder aktivieren (Zeile 55-81)
6. ✅ extract_event_data(): `base["version"] = LOG_VERSION` (Zeile 492)

**Test-Cases:**
```python
# Test 1: SessionStart enthält source + transcript_path
event = extract_event_data({
    "hook_event_name": "SessionStart",
    "session_id": "test",
    "source": "startup",
    "transcript_path": "/path/transcript.jsonl",
    "permission_mode": "default",
    "cwd": "/home/user"
})
assert event["source"] == "startup"
assert event["version"] == "2.0.0"

# Test 2: PreCompact enthält trigger
event = extract_event_data({
    "hook_event_name": "PreCompact",
    "session_id": "test",
    "trigger": "manual",
    "custom_instructions": "verbose"
})
assert event["trigger"] == "manual"
```

---

### Phase 2: Production Readiness (⏱️ ~2-3 Stunden)

**Ziel:** Log-Rotation implementieren

**Änderungen:**
1. ✅ Konstante: `LOG_MAX_SIZE_MB = int(os.getenv("CC_LOG_MAX_SIZE_MB", "100"))`
2. ✅ Funktion: `rotate_logs_if_needed()` (20 Zeilen)
3. ✅ Funktion: `gzip_file(filepath)` (10 Zeilen)
4. ✅ write_log_line() anpassen: rotate_logs_if_needed() vor write

**Konfiguration:**
```bash
# .bashrc / .zshrc
export CC_LOG_MAX_SIZE_MB="100"  # Default: 100MB
```

**Log-Dateien nach Rotation:**
```
.claude/logs/
├── claude-output.jsonl           (< 100MB, aktuell)
├── claude-output.20251106_143022.jsonl.gz  (archiviert, komprimiert)
├── claude-output.20251105_120500.jsonl.gz  (archiviert)
└── ...
```

---

### Phase 3: Advanced Features (⏱️ ~2-4 Wochen)

#### 3.1 Background-Task-Tracking

**Änderungen:**
1. ✅ Konstante: `BG_TASK_CACHE = LOG_FILE.parent / "background_tasks.json"`
2. ✅ PostToolUse Handler erweitern (Zeile 548-556)

#### 3.2 Tool-Normalisierung Registry

**Refactoring-Arbeiten:**
1. ✅ Extrahiere normalize_bash() → separate Funktion
2. ✅ Extrahiere normalize_file_op() → separate Funktion
3. ✅ Extrahiere normalize_websearch() → separate Funktion
4. ✅ Extrahiere normalize_task() → separate Funktion
5. ✅ Extrahiere normalize_mcp() → separate Funktion
6. ✅ Erstelle TOOL_NORMALIZERS dict
7. ✅ Refactor normalize_tool_output() zu Registry-Pattern

---

## Testing & Validation

### Phase 1 Test-Plan

```bash
# Test-Mode aktivieren
export HOOK_TEST=1

# Test 1: SessionStart mit allen Feldern
echo '{"hook_event_name":"SessionStart","session_id":"test","source":"startup","transcript_path":"/tmp/transcript.jsonl","permission_mode":"default","cwd":"/home/user"}' | \
  python logger.py | jq '.result.data | {source, transcript_path, permission_mode, version}'

# Erwartung:
# {"source":"startup","transcript_path":"/tmp/transcript.jsonl","permission_mode":"default","version":"2.0.0"}

# Test 2: Version in jedem Event
echo '{"hook_event_name":"PreToolUse","session_id":"test","tool_name":"Bash","tool_input":{"command":"ls"}}' | \
  python logger.py | jq '.result.data.version'

# Erwartung:
# "2.0.0"
```

### Phase 2 Test-Plan

```bash
# Test 3: Log-Rotation bei 100MB
# 1. Erzeuge großer Log (>100MB)
# 2. Schreibe neuen Event
# 3. Prüfe: claude-output.TIMESTAMP.jsonl.gz existiert
# 4. Prüfe: Neue claude-output.jsonl erstellt

# Test 4: gzip Kompression funktioniert
gunzip -t /path/logs/claude-output.*.jsonl.gz
# Erwartung: Alle .gz Dateien valide
```

---

## Rollout-Strategie

### Pre-Deployment
- [ ] Code Review für Phase 1 & 2
- [ ] Test-Suite durchlaufen
- [ ] Backward-Compatibility prüfen (LOG_VERSION field)

### Deployment
1. Phase 1 + 2 zusammen releasen (v2.0.0)
2. CHANGELOG.md mit Breaking Changes
3. Migration-Guide für bestehende Logs

### Post-Deployment
- [ ] Monitoring von Log-Rotation
- [ ] Performance-Metriken tracken
- [ ] User-Feedback sammeln

---

## Acceptance Criteria

| Kriterium | Phase | Status |
|---|---|---|
| SessionStart: `source`, `transcript_path`, `permission_mode` | 1 | - |
| SessionEnd: `transcript_path`, `cwd` | 1 | - |
| PreCompact: `trigger`, `custom_instructions` | 1 | - |
| Alle Events: `version` field | 1 | - |
| FIELD_CONFIG aktualisiert | 1 | - |
| Log-Rotation bei 100MB (konfigurierbar) | 2 | - |
| gzip Kompression funktioniert | 2 | - |
| Background-Tasks cachen | 3 | - |
| Tool-Normalizer Registry | 3 | - |
| Test-Suite 100% grün | Alle | - |

---

## Dokumentation & Links

- [Original Analyse](./claude-code-logger-analyse.md) (v1.0)
- [logger.py](../.claude/hooks/logger.py) (aktuell)
- [settings.local.json](../.claude/settings.local.json)

---

**Nächste Schritte:**
1. ✅ Plan bestätigt
2. → Phase 1 implementieren
3. → Tests schreiben & ausführen
4. → Phase 2 + 3 folgen
