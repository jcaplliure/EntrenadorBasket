# Propuesta de Mejoras - Sistema de Entrenamientos

## 1. GESTIÓN DE ASISTENCIA

### Problema Actual:
- No se puede registrar asistencia sin usar Modo Pista
- Al añadir jugador tardío no se ven los ausentes
- No hay forma de gestionar asistencia independientemente

### Solución Propuesta:

#### A) Nueva Página "Registrar Asistencia" (sin Modo Pista)
- **Ubicación**: Pestaña nueva en "Gestión de Equipo" o botón destacado
- **Funcionalidad**:
  - Seleccionar plan de entrenamiento
  - Lista de jugadores del equipo con checkboxes (todos preseleccionados)
  - Desmarcar los que no están
  - Crear sesión y guardar asistencia
  - Redirigir a página de edición de sesión para añadir ejercicios realizados

#### B) Modal de Inicio de Sesión en Modo Pista
- **Flujo mejorado**:
  1. Click en "Modo Pista" → Abre modal de asistencia
  2. Si hay varios equipos: selector de equipo
  3. Si solo hay un equipo: se preselecciona automáticamente
  4. Lista de jugadores con checkboxes (TODOS preseleccionados por defecto)
  5. Desmarcar los que no están presentes
  6. Click "Iniciar Sesión" → Comienza Modo Pista con sesión activa

#### C) Modal de Añadir Jugador Tardío (MEJORADO)
- **Cambios**:
  - ❌ **ELIMINAR** opción de crear nuevo jugador
  - ✅ Mostrar lista de jugadores AUSENTES del equipo
  - ✅ Seleccionar de la lista (checkboxes o botones)
  - ✅ Al seleccionar, se marca como presente automáticamente
  - ✅ Si no hay ausentes, mostrar mensaje "Todos los jugadores ya están presentes"
  - **Nota**: Para añadir nuevos jugadores al equipo → ir a "Gestión de Equipo" → "Plantilla"

---

## 2. EJERCICIOS NO REALIZADOS

### Problema Actual:
- No se registra qué ejercicios no se hicieron
- No se puede indicar que un ejercicio se saltó

### Solución Propuesta:

#### Nuevo Modelo de Datos:
```python
class SessionItemExecution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('training_session.id'), nullable=False)
    training_item_id = db.Column(db.Integer, db.ForeignKey('training_item.id'), nullable=False)
    was_completed = db.Column(db.Boolean, default=True)  # True = se hizo, False = no se hizo
    actual_duration = db.Column(db.Integer, nullable=True)  # Tiempo real en minutos (null si no se hizo)
    notes = db.Column(db.Text, nullable=True)  # Notas opcionales
    completed_at = db.Column(db.DateTime, nullable=True)  # Cuándo se completó
```

#### En Modo Pista:
- **Botón "No Realizado"** en cada ejercicio (junto a "Gamificar")
- Al hacer click:
  - Marca el ejercicio como no realizado
  - Oculta el timer (o lo desactiva)
  - Guarda automáticamente en `SessionItemExecution`
- Al finalizar sesión: guarda todos los ejercicios (realizados y no realizados)

---

## 3. HISTÓRICO Y EDICIÓN DE ENTRENAMIENTOS

### Problema Actual:
- No se puede editar un entrenamiento finalizado
- No se puede modificar tiempos o ejercicios después

### Solución Propuesta:

#### A) Nueva Pestaña "Historial" en Gestión de Equipo
- **Ubicación**: Nueva pestaña después de "Estadísticas"
- **Contenido**:
  - Lista de sesiones finalizadas ordenadas por fecha (más reciente primero)
  - Cada sesión muestra:
    - 📅 **Fecha y hora**
    - 📋 **Plan usado** (nombre del plan)
    - 👥 **Jugadores presentes** (lista con nombres y dorsales)
    - ✅ **Ejercicios realizados** (lista expandida):
      - Para cada ejercicio:
        - Nombre del ejercicio
        - ⏱️ Tiempo real (minutos)
        - Si tiene gamificación:
          - 🎮 **Resultados de gamificación**:
            - Tabla con jugadores ordenados de mejor a peor (por puntos)
            - Columnas: Posición, Jugador, Resultado (raw_score), Puntos
    - 🔘 **Botón "Editar"**
  
  **Formato Visual Propuesto**:
  ```
  ┌─────────────────────────────────────────────────────┐
  │ 📅 22/01/2026 18:00                                 │
  │ 📋 Plan: Defensa Zonal Martes                       │
  │                                                     │
  │ 👥 Jugadores presentes (8):                         │
  │    Juan #5, María #10, Pedro #15, ...              │
  │                                                     │
  │ ✅ Ejercicios realizados:                          │
  │    • Cintas poste bajo - 10 min                     │
  │      🎮 Gamificación:                              │
  │         1. Juan #5 - 15 canastas (15 pts)          │
  │         2. María #10 - 12 canastas (14 pts)        │
  │         3. Pedro #15 - 10 canastas (13 pts)        │
  │    • Bote y coordinación - 15 min                  │
  │    • Tiro libre - 8 min                            │
  │      🎮 Gamificación:                              │
  │         1. María #10 - 8/10 (15 pts)              │
  │         2. Juan #5 - 7/10 (14 pts)                 │
  │                                                     │
  │ [🔘 Editar]                                         │
  └─────────────────────────────────────────────────────┘
  ```

#### B) Página de Edición de Sesión Finalizada
- **Ruta**: `/session/<id>/edit`
- **Contenido**:
  
  **Sección 1: Asistencia**
  - Lista de jugadores con checkboxes
  - Marcar/desmarcar presentes
  
  **Sección 2: Ejercicios del Plan**
  - Lista de todos los ejercicios del plan usado
  - Para cada ejercicio:
    - ☑️ Checkbox "Realizado"
    - ⏱️ Input de tiempo real (minutos)
    - 📝 Textarea para notas (opcional)
    - Si está gamificado: mostrar resultados
  
  **Sección 3: Gamificación** (si hay ejercicios gamificados)
  - Lista de ejercicios que fueron gamificados
  - Para cada ejercicio:
    - Nombre del ejercicio
    - Tabla con jugadores y sus resultados:
      - Columna: Jugador
      - Columna: Resultado (raw_score) - editable
      - Columna: Puntos asignados - calculado automáticamente
      - Columna: Criterio (Mayor/Menor) - editable
    - Botón "Recalcular Puntos" (recalcula según criterio)
    - Botón "Eliminar Gamificación" (opcional)
  
  **Botones de Acción**:
  - "Guardar Cambios" (guarda todo)
  - "Cancelar" (vuelve al historial)

#### C) Endpoints Necesarios:
- `GET /session/<id>/edit` - Mostrar página de edición
- `POST /api/update_session_execution` - Actualizar ejercicio realizado/no realizado
- `POST /api/update_gamification` - Actualizar resultados de gamificación
- `GET /api/get_session_executions/<session_id>` - Obtener ejercicios de una sesión

---

## 4. ESTADÍSTICAS DE EJERCICIOS

### Problema Actual:
- No hay forma de saber qué ejercicios se hacen más
- No se puede analizar tiempo por categoría (Bote, Tiro, etc.)

### Solución Propuesta:

#### A) Nueva Pestaña "Estadísticas de Ejercicios"
- **Ubicación**: Nueva pestaña en "Gestión de Equipo"
- **Filtros**:
  - Periodo: Semana / Mes / Año / Personalizado (fecha inicio - fecha fin)
  - Selector de modo de conteo multi-tag (ver abajo)

#### B) Métricas Mostradas:

**1. Tiempo Total por Tag/Categoría**
- Gráfico de barras o donut
- Muestra: Bote, Tiro, Defensa, Pase, etc.
- Tiempo en minutos/horas

**2. Ejercicios Más Realizados**
- Top 10 ejercicios más usados
- Con número de veces realizado y tiempo total

**3. Distribución de Tiempo**
- Gráfico circular mostrando % de tiempo por categoría

**4. Evolución Temporal**
- Gráfico de líneas mostrando tiempo por tag a lo largo del tiempo
- Útil para ver tendencias

#### C) Sistema Multi-Tag (Ejercicios con múltiples categorías)

**Problema**: Un ejercicio puede tener "Bote" y "Tiro" como tags. ¿Cómo contamos el tiempo?

**Solución con Selector**:
- **Modo "Dividido"** (por defecto):
  - Si un ejercicio tiene 2 tags y duró 10 minutos
  - Cuenta 5 minutos para cada tag
  - Fórmula: `tiempo_total / número_de_tags`
  
- **Modo "Completo"**:
  - Si un ejercicio tiene 2 tags y duró 10 minutos
  - Cuenta 10 minutos para cada tag
  - Fórmula: `tiempo_total` para cada tag

**Selector en la interfaz**:
- Radio buttons o toggle switch
- "Dividir tiempo entre tags" / "Contar tiempo completo para cada tag"
- Al cambiar, recalcula las estadísticas

---

## 5. ESTRUCTURA DE DATOS COMPLETA

### Modelos Nuevos/Modificados:

```python
# NUEVO MODELO
class SessionItemExecution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('training_session.id'), nullable=False)
    training_item_id = db.Column(db.Integer, db.ForeignKey('training_item.id'), nullable=False)
    was_completed = db.Column(db.Boolean, default=True)
    actual_duration = db.Column(db.Integer, nullable=True)  # minutos, null si no se hizo
    notes = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    session = db.relationship('TrainingSession', backref='executions')
    training_item = db.relationship('TrainingItem', backref='executions')

# TrainingSession ya existe, no necesita cambios
# SessionScore ya existe para gamificación
```

### Relaciones:
- `TrainingSession` → `SessionItemExecution` (uno a muchos)
- `TrainingItem` → `SessionItemExecution` (uno a muchos)
- `SessionItemExecution` → `Drill` (a través de `TrainingItem`)

---

## 6. FLUJOS PROPUESTOS

### Flujo A: Modo Pista Completo

1. **Inicio**:
   - Click "Modo Pista" → Modal de asistencia
   - Todos los jugadores preseleccionados
   - Desmarcar ausentes → "Iniciar Sesión"

2. **Durante Entrenamiento**:
   - Ver ejercicios uno por uno
   - Timer para cada ejercicio
   - Botón "Gamificar" (si hay sesión activa)
   - Botón "No Realizado" (marca ejercicio como no hecho)
   - Al avanzar: guarda tiempo real automáticamente

3. **Finalización**:
   - Pantalla de resumen
   - Muestra: ejercicios realizados, no realizados, tiempo total
   - "Guardar y Salir" → Crea `SessionItemExecution` para cada ejercicio
   - Marca sesión como "finished"

### Flujo B: Registro Manual (sin Modo Pista)

1. **Gestión de Equipo** → Pestaña "Registrar Asistencia"
2. Seleccionar plan
3. Marcar jugadores presentes
4. "Crear Sesión" → Redirige a edición de sesión
5. En edición:
   - Marcar ejercicios realizados
   - Añadir tiempos reales
   - Añadir gamificaciones (opcional)
   - Guardar

### Flujo C: Edición de Sesión Finalizada

1. **Gestión de Equipo** → Pestaña "Historial"
2. Ver lista de sesiones
3. Click "Editar" en una sesión
4. Modificar:
   - Asistencia (marcar/desmarcar jugadores)
   - Ejercicios realizados/no realizados
   - Tiempos reales
   - Resultados de gamificación
5. "Guardar Cambios"

### Flujo D: Añadir Jugador Tardío

1. Durante Modo Pista → Click botón flotante "+"
2. Modal muestra:
   - **Lista de jugadores AUSENTES** (del equipo, no presentes en sesión)
   - Cada jugador con botón "Añadir"
   - Mensaje si no hay ausentes
3. Click en jugador → Se marca como presente
4. Se actualiza automáticamente en la sesión
5. ❌ **NO hay opción de crear nuevo jugador** (ir a Gestión de Equipo)

---

## 7. ENDPOINTS NECESARIOS

### Asistencia:
- `GET /api/get_absent_players?session_id=X` - Obtener jugadores ausentes
- `POST /api/add_absent_player` - Añadir jugador ausente a sesión

### Ejecución de Ejercicios:
- `POST /api/save_exercise_execution` - Guardar si ejercicio se hizo/no se hizo
- `GET /api/get_session_executions/<session_id>` - Obtener ejercicios de sesión
- `POST /api/update_exercise_execution` - Actualizar ejercicio (edición)

### Historial:
- `GET /session/<id>/edit` - Página de edición de sesión
- `GET /api/get_session_history/<team_id>` - Lista de sesiones del equipo

### Estadísticas:
- `GET /api/get_exercise_stats/<team_id>` - Estadísticas de ejercicios
- Parámetros: `start_date`, `end_date`, `mode` (divided/complete)

### Gamificación (edición):
- `GET /api/get_session_gamifications/<session_id>` - Obtener gamificaciones
- `POST /api/update_gamification` - Actualizar resultado de gamificación
- `POST /api/delete_gamification` - Eliminar gamificación

---

## 8. INTERFAZ DE USUARIO

### Modo Pista - Botón "No Realizado":
- Ubicado junto al botón "Gamificar"
- Al hacer click:
  - Cambia a estado "No realizado"
  - Se desactiva el timer
  - Se guarda automáticamente
  - Botón cambia a "Marcar como Realizado" (para revertir)

### Historial - Lista de Sesiones:
```
┌─────────────────────────────────────────┐
│ 📅 22/01/2026 18:00                     │
│ 📋 Plan: Defensa Zonal Martes           │
│ 👥 8 jugadores presentes                │
│ ✅ 12 de 15 ejercicios realizados       │
│ 🎮 3 ejercicios gamificados             │
│ ⏱️ Duración: 75 minutos                 │
│ [🔘 Editar]                             │
└─────────────────────────────────────────┘
```

### Edición de Sesión:
- Tabs o secciones:
  1. **Asistencia** (checkboxes de jugadores)
  2. **Ejercicios** (lista con checkboxes, tiempos, notas)
  3. **Gamificación** (tablas editables de resultados)

---

## 9. PREGUNTAS PENDIENTES

1. ✅ **Multi-tag**: Implementado con selector (Dividido/Completo)
2. ✅ **Edición de gamificación**: Incluido en edición de sesión
3. ✅ **Añadir jugador tardío**: Solo seleccionar de ausentes, no crear nuevos
4. ⏳ **Tiempos**: ¿Guardar solo minutos enteros o también segundos? (Sugerencia: minutos enteros)
5. ⏳ **Notas en ejercicios**: ¿Quieres poder añadir notas por ejercicio en una sesión? (Sugerencia: Sí, campo opcional)

---

## 10. RESUMEN DE CAMBIOS

### Nuevos Modelos:
- ✅ `SessionItemExecution` - Para registrar ejercicios realizados/no realizados

### Nuevas Páginas:
- ✅ Pestaña "Historial" en Gestión de Equipo
- ✅ Página de edición de sesión (`/session/<id>/edit`)
- ✅ Pestaña "Estadísticas de Ejercicios" en Gestión de Equipo

### Mejoras en Existentes:
- ✅ Modal de inicio de sesión en Modo Pista (todos preseleccionados)
- ✅ Modal de añadir jugador tardío (solo ausentes, sin crear nuevos)
- ✅ Botón "No Realizado" en Modo Pista
- ✅ Guardar tiempos reales al finalizar

### Nuevos Endpoints:
- ✅ Todos los mencionados en sección 7

---

¿Te parece bien esta estructura actualizada? ¿Algún ajuste antes de implementar?
