# 🚌 Bondiero Bot — ETA Engine Rewrite

**Fecha:** 12 Mar 2026  
**Commit:** `5b3a228` — feat: rewrite ETA engine with tripUpdates primary + vehiclePositions fallback

## Resumen de Cambios

### Bugs Corregidos
| Bug | Causa | Fix |
|---|---|---|
| Duplicate ETAs ("7min 7min 7min") | No direction filter → same buses in both dirs | Filter by `direction_id` per stop |
| Imprecise ETAs | OSRM car routing ≠ bus route | Cascading fallback: speed → OSRM → linear |
| Missing real-time data | Only used `vehiclePositions` | Added `tripUpdates` as primary source |

### Nueva Arquitectura

```
User → Geocode + Find stops
         ↓
    Try tripUpdates (geographic matching 500m)
         ↓ (has data?)
    YES → ⏱ Real-time ETA
    NO  → vehiclePositions fallback
              ↓ (has direction?)
         YES → Filter by direction_id
         NO  → Use all vehicles
              ↓ (has speed?)
         YES → 📐 Speed-based ETA
         NO  → OSRM available?
              YES → 📐 OSRM ETA
              NO  → 📐 Linear ETA (18km/h)
```

### Descubrimiento: stop_id format mismatch
La DB usa IDs como `201005`, pero la API tripUpdates usa formatos mixtos (`06658000668`).
Solución: **matching geográfico** — buscar la parada API más cercana dentro de 500m.

## Resultados de Tests

```
✅ PASS: ETA Helpers (speed-based, linear, edge cases)
✅ PASS: tripUpdates Geographic Matching
✅ PASS: vehiclePositions Direction Filtering (17 vehículos → 11 dir0, 6 dir1)
✅ PASS: Full ETA Flow (ETAs únicos por dirección, sin duplicados)
```

### Antes vs Después

| Métrica | Antes | Después |
|---|---|---|
| Filtrado por dirección | ❌ Ninguno | ✅ Per direction_id |
| Dedup de vehículos | ❌ Ninguno | ✅ Por vehicle.id |
| tripUpdates (ETA real) | ❌ No usado | ✅ Fuente primaria |
| Cadena de fallback | Solo OSRM | Speed → OSRM → Linear |
| ETAs duplicados | ✅ Frecuente | ❌ Eliminado |

## Próximos Pasos
- Deploy a Fly.io (`fly deploy`)
- Test live en Telegram
- Monitorear cobertura de tripUpdates en horas pico
