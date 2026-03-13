# 🚌 Mejora del Cálculo de ETA — Bondiero Bot

## Diagnóstico Realizado (12 Mar 2026, 21:04 ART)

### Resultados de la API

| Endpoint | Estado | Datos |
|---|---|---|
| `/colectivos/tripUpdates` | ✅ 200 OK | **7540 entidades** (6.6 MB) |
| `/colectivos/vehiclePositions` | ✅ 200 OK | **12722 vehículos** (1.2 MB) |
| `/colectivos/vehiclePositionsSimple` | ✅ 200 OK | JSON disponible |

### tripUpdates — Hallazgos Clave

**Los tripUpdates tienen datos en TIEMPO REAL**, no de planilla. Cada entidad tiene un `timestamp` reciente y un `arrival_delay` dinámico que varía por parada. Las empresas reportan posición GPS y el sistema calcula predicciones.

Ejemplo real capturado:
```
trip_id: 100000-1 | route_id: 1578 | direction_id: 0
timestamp: 21:02 (ART) → stop 06756000195 llega a 21:03:14 (delay 4750s)
```

### vehiclePositions — Hallazgos Clave

| Campo | Disponibilidad |
|---|---|
| `vehicle.id` | ✅ 12722/12722 (100%) — sin duplicados |
| `trip_id` | ⚠️ 8133/12722 (64%) |
| `direction_id` | ⚠️ 3870/12722 (30%) |
| `speed` | ⚠️ 7879/12722 (62%) |
| `bearing` | ❌ 0/12722 (0%) |

### Root Cause

| Bug | Causa | Impacto |
|---|---|---|
| ETAs duplicados ("7min 7min 7min") | Sin filtro de dirección + mismos colectivos en ambas paradas | Alto |
| ETAs imprecisos | OSRM calcula ruta en auto, no recorrido del colectivo | Medio |
| Datos incompletos | 36% sin trip_id, 70% sin direction_id | Medio |

---

## Plan Implementado: Opción A+B

### Estrategia

```
1. Intentar tripUpdates (ETA directo por parada)
   └─ Si hay datos → arrival_time - now = minutos
2. Fallback: vehiclePositions mejorado
   └─ Filtrar por direction_id
   └─ Deduplicar por vehicle.id
   └─ Speed-based → OSRM → distancia/velocidad lineal
```

### Cambios en `bot.py`

1. **`fetch_trip_updates()`**: Consume `/colectivos/tripUpdates` con matching geográfico (500m)
2. **`fetch_realtime_vehicles()`**: Dedup por `vehicle.id` + extrae `direction_id`, `speed`
3. **`get_etas_for_stops()`**: Orquesta tripUpdates primary → vehiclePositions fallback
4. **`calculate_eta_speed()`** + **`calculate_eta_linear()`**: Fallbacks sin OSRM
5. **Formateo**: "⏱ Llegan en" (realtime) vs "📐 Estimado" (fallback)
