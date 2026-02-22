#!/usr/bin/env python3
"""
Importa el partido Infantil vs Claret (26/01/2026) desde logs de jugadas.

Uso recomendado:
  ./.venv/bin/python import_match_infantil_claret_2026.py --replace

Opciones:
  --dry-run   valida todo sin escribir en BD
  --replace   si existe el partido, borra sus eventos y lo vuelve a cargar
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from app import ActionDefinition, Match, MatchEvent, Player, Team, app, db, get_actions_for_team


MATCH_DATE = "2026-01-26"
TEAM_NAME = "Infantil"
OPPONENT = "Claret"
EXPECTED_SCORE_US = 50
EXPECTED_SCORE_THEM = 40


RAW_LOGS = """
2, Q1, Alejandro, Tiro 1, -0.25
3, Q1, Alejandro, Tiro, -0.25
4, Q1, Quiq Pica, Reb.Of., +1.00
5, Q1, Jordi, Bal. Per, -0.50
6, Q1, Alberto, Reb.Def, +1.00
7, Q1, Alberto, Bal. Per, -0.50
8, Q1, Alejandro, Reb. Def, +1.00
9, Q1, Alejandro, Bal.Per, -0.50
10, Q1, Alejandro, Reb.Def, +1.00
11, Q1, Martin, Bal. Per, -0.50
12, Q1, Jordi, Falta, 0.00
13, Q1, Jordi, Tiro 2, -0.50
14, Q1, Alejandro, Reb.Def, +1.00
15, Q1, Quiq Pic., Tiro 2, -0.50
16, Q1, Alejandro, Reb. Def, +1.00
17, Q1, Jordi, Tiro 2, +2.00
18, Q1, Alejandro, Tapon, +1.00
19, Q1, Quiq Pic., Bal. Per, -0.50
20, Q1, Alejandro, Prov.Pe, +1.00
21, Q1, Jordi, Can. Fac, -2.00
22, Q1, Martin, Reb. Def, +1.00
23, Q1, Jordi, Reb.Of., +1.00
24, Q1, Jordi, Tiro 2, -0.50
25, Q1, Jordi, Tiro 2, +2.00
26, Q1, Jordi, Reb.Def, +1.00
27, Q1, Jordi, Reb. Def, +1.00
28, Q1, Alejandro, Tiro 2, +2.00
29, Q1, Jordi, Tap.Rec, -0.25
30, Q1, Jordi, Tiro 2, +2.00
31, Q2, Eric, Tiro 2, +2.00
32, Q2, Eric, Reb.Def, +1.00
33, Q2, Lautaro, Bal. Per, -0.50
34, Q2, Ricardo, Bal. Per, -0.50
35, Q2, Quiq Silv., Prov.Pe, +1.00
36, Q2, Beren, Bal. Per, -0.50
37, Q2, Quiq Silv., Tiro 2, -0.50
38, Q2, Ricardo, Robo, +1.00
39, Q2, Eric, Tapon, +1.00
40, Q2, Beren, Bal.Per, -0.50
41, Q2, Lautaro, Robo, +1.00
42, Q2, Lautaro, Tiro 2, -0.50
43, Q2, Quiq Silv., Robo, +1.00
44, Q2, Eric, Tiro 2, +2.00
45, Q2, Lautaro, Asist, +2.00
47, Q2, Eric, Bal. Per, -0.50
48, Q2, Ricardo, Robo, +1.00
49, Q2, Ricardo, Bal. Per, -0.50
50, Q2, Eric, Robo, +1.00
51, Q2, Eric, Asist, +2.00
52, Q2, Quiq Silv., Tiro 2, +2.00
53, Q2, Beren, Robo, +1.00
54, Q2, Eric, Bal.Per, -0.50
55, Q2, Ricardo, Robo, +1.00
56, Q2, Lautaro, Bal.Per, -0.50
57, Q2, Quiq Silv., Robo, +1.00
58, Q2, Beren, Bal. Per, -0.50
60, Q2, Beren, Can. Fac, -2.00
61, Q2, Lautaro, Reb.Of., +1.00
62, Q2, Ricardo, Tiro 3, -0.50
63, Q2, Ricardo, Reb.Def, +1.00
64, Q2, Ricardo, Bal. Per, -0.50
65, Q2, Ricardo, Robo, +1.00
66, Q2, Lautaro, Bal. Per, -0.50
67, Q2, Eric, Bal. Per, -0.50
68, Q2, Lautaro, Reb.Def, +1.00
69, Q2, Lautaro, Bal. Per, -0.50
70, Q2, Eric, Asist, +2.00
71, Q2, Eric, Tiro 1, -0.25
72, Q2, Eric, Tiro 1, +1.00
73, Q3, Jorge, Reb.Def, +1.00
74, Q3, Alejandro, Tiro 2, +2.00
76, Q3, Jordi, Bal. Per, -0.50
78, Q3, Jorge, Bal. Per, -0.50
79, Q3, Alejandro, Reb.Of., +1.00
80, Q3, Alejandro, Can. Fac, -2.00
81, Q3, Alejandro, Robo, +1.00
82, Q3, Alejandro, Bal. Per, -0.50
83, Q3, Jordi, Tapon, +1.00
84, Q3, Alejandro, Tapon, +1.00
85, Q3, Jordi, Reb.Def, +1.00
86, Q3, Jordi, Asist, +2.00
87, Q3, Jorge, Tiro 2, +2.00
88, Q3, Jordi, Robo, +1.00
89, Q3, Alejandro, Tiro 2, +2.00
90, Q3, Alejandro, Tapon, +1.00
91, Q3, Alejandro, Reb.Def, +1.00
92, Q3, Jorge, Tiro 2, -0.50
93, Q3, Alejandro, Robo, +1.00
94, Q3, Alejandro, Tiro 2, +2.00
95, Q3, Alejandro, Tiro 1, +1.00
96, Q3, Alejandro, Reb. Def, +1.00
97, Q3, Alejandro, Bal. Per, -0.50
99, Q3, Alejandro, Robo, +1.00
100, Q3, Alejandro, Bal.Per, -0.50
102, Q3, Alejandro, Tap Rec, -0.25
103, Q3, Jorge, Asist, +2.00
104, Q3, Martin, Tiro 2, +2.00
105, Q3, Alejandro, Reb.Def, +1.00
106, Q3, Alejandro, Tiro 2, +2.00
107, Q3, Alejandro, Robo, +1.00
108, Q3, Martin, Tiro 2, -0.50
109, Q3, Lautaro, Bal. Per, -0.50
110, Q3, Quiq Silv., Robo, +1.00
111, Q3, Ricardo, Bal. Per, -0.50
112, Q3, Lautaro, Tiro 2, -0.50
113, Q3, Lautaro, Tiro 1, +1.00
114, Q3, Lautaro, Reb.Of., +1.00
115, Q3, Eric, Can. Fac, -2.00
116, Q3, Quiq Silv., Reb.Of., +1.00
117, Q3, Alberto, Bal. Per, -0.50
119, Q3, Eric, Tap.Rec, -0.25
120, Q3, Ricardo, Reb.Def, +1.00
121, Q3, Eric, Bal. Per, -0.50
122, Q3, Lautaro, Robo, +1.00
123, Q3, Lautaro, Bal. Per, -0.50
124, Q3, Quiq Silv., Robo, +1.00
125, Q3, Quiq Silv., Bal. Per, -0.50
126, Q3, Eric, Tiro 3, -0.50
127, Q3, Eric, Robo, +1.00
128, Q3, Eric, Bal. Per, -0.50
129, Q4, Lautaro, Tiro 2, -0.50
130, Q4, Quiq Silv., Reb.Of., +1.00
131, Q4, Eric, Tiro 2, -0.50
132, Q4, Ricardo, Reb.Def, +1.00
133, Q4, Ricardo, Bal. Per, -0.50
135, Q4, Alberto, Bal. Per, -0.50
136, Q4, Quiq Silv., Robo, +1.00
137, Q4, Ricardo, Bal. Per, -0.50
139, Q4, Ricardo, Bal. Per, -0.50
140, Q4, Eric, Reb.Def, +1.00
141, Q4, Quiq Silv., Can. Fac, -2.00
142, Q4, Alberto, Robo, +1.00
143, Q4, Quiq Silv., Bal. Per, -0.50
144, Q4, Lautaro, Tiro 3, -0.50
145, OT, Beren, Robo, +1.00
146, OT, Alejandro, Prov.Pe, +1.00
147, OT, Jorge, Tiro 2, -0.50
148, OT, Quiq Pic., Robo, +1.00
149, OT, Jordi, Bal. Per, -0.50
150, OT, Alejandro, Tapon, +1.00
152, OT, Alejandro, Tiro 3, -0.50
153, OT, Alejandro, Tiro 3, -0.50
154, OT, Alejandro, Tiro 2, -0.50
155, OT, Alejandro, Reb.Of., +1.00
156, OT, Alejandro, Can. Fac, -2.00
157, OT, Beren, Reb.Def, +1.00
158, OT, Alejandro, Prov.Pe, +1.00
159, OT, Quiq Pic., Robo, +1.00
160, OT, Beren, Can. Fac, -2.00
161, OT, Jorge, Reb.Def, +1.00
162, OT, Quiq Pic., Tiro 3, +3.00
163, OT, Quiq Pic., Bal. Per, -0.50
164, OT, Quiq Pic., Bal. Per, -0.50
165, OT, Alejandro, Reb.Def, +1.00
166, OT, Alejandro, Bal. Per, -0.50
167, OT, Jordi, Tiro 2, -0.50
168, OT, Beren, Reb.Def, +1.00
169, OT, Martin, Tiro 2, -0.50
170, OT, Quiq Silv., Tiro 2, +2.00
171, OT, Quiq Silv., Reb.Of., +1.00
173, OT, Martin, Can. Fac, -2.00
174, OT, Quiq Silv., Reb.Of., +1.00
175, OT, Lautaro, Bal. Per, -0.50
176, OT, Eric, Robo, +1.00
177, OT, Lautaro, Tiro 3, -0.50
178, OT, Quiq Silv., Reb. Def, +1.00
179, OT, Lautaro, Bal. Per, -0.50
180, OT, Alberto, Prov.Pe, +1.00
183, OT, Quiq Silv., Reb.Of., +1.00
184, OT, Alberto, Robo, +1.00
185, OT, Alberto, Prov.Pe, +1.00
186, OT, Alberto, Robo, +1.00
187, OT, Lautaro, Prov. Pe, +1.00
188, OT, Lautaro, Bal. Per, -0.50
189, OT, Alberto, Bal. Per, -0.50
190, OT, Martin, Reb.Def, +1.00
191, OT, Lautaro, Tiro 2, -0.50
192, OT, Lautaro, Tiro, -0.25
193, OT, Lautaro, Tiro 1, -0.25
194, OT, Martin, Reb.Of., +1.00
195, OT, Eric, Tiro 2, -0.50
196, OT, Quiq Silv., Reb.Of., +1.00
197, OT, Martin, Tiro 3, -0.50
198, OT, Quiq Silv., Robo, +1.00
199, OT, Quiq Silv., Tiro 2, -0.50
200, OT, Quiq Silv., Bal. Per, -0.50
201, OT, Quiq Silv., Reb.Def, +1.00
202, OT2, Lautaro, Tiro 2, +2.00
203, OT2, Alberto, Prov.Pe, +1.00
204, OT2, Lautaro, Tiro 2, +2.00
205, OT2, Eric, Reb.Def, +1.00
206, OT2, Eric, Bal. Per, -0.50
207, OT2, Eric, Bal. Per, -0.50
208, OT2, Quiq Silv., Robo, +1.00
209, OT3, Jorge, Tiro 2, -0.50
210, OT3, Beren, Reb.Def, +1.00
211, OT3, Beren, Bal. Per, -0.50
212, OT3, Beren, Bal. Per, -0.50
213, OT3, Alejandro, Tiro 2, -0.50
214, OT3, Alejandro, Reb.Of., +1.00
215, OT3, Alejandro, Tiro 2, +2.00
216, OT3, Quiq Pic., Reb.Def, +1.00
217, OT3, Alejandro, Tiro 1, -0.25
218, OT3, Alejandro, Tiro 1, -0.25
219, OT3, Jordi, Reb.Of., +1.00
221, OT3, Jordi, Bal. Per, -0.50
223, OT3, Alejandro, Tiro 2, -0.50
224, OT3, Alejandro, Reb.Of., +1.00
225, OT3, Alejandro, Tiro 2, -0.50
226, OT3, Alejandro, Reb.Of., +1.00
227, OT3, Jorge, Tiro 3, -0.50
228, OT3, Jorge, Can.Fac, -2.00
230, OT3, Beren, Tiro 2, -0.50
231, OT3, Alejandro, Tiro 2, +2.00
233, OT3, Alejandro, Reb. Def, +1.00
234, OT3, Alejandro, Tiro 3, -0.50
235, OT3, Jordi, Robo, +1.00
236, OT3, Alejandro, Bal. Per, -0.50
237, OT3, Alejandro, Bal. Per, -0.50
238, OT3, Alejandro, Bal. Per, -0.50
239, OT3, Alejandro, Reb.Def, +1.00
240, OT3, Alejandro, Tiro 2, +2.00
241, OT3, Quiq Pic., Robo, +1.00
242, OT3, Lautaro, Bal. Per, -0.50
243, OT3, Lautaro, Tiro 3, -0.50
244, OT3, Lautaro, Prov.Pe, +1.00
245, OT4, Quiq Silv., Reb.Def, +1.00
246, OT4, Quiq Silv., Robo, +1.00
247, OT4, Ricardo, Bal.Per, -0.50
248, OT4, Quiq Silv., Robo, +1.00
249, OT4, Martin, Tiro 2, +2.00
250, OT4, Alberto, Robo, +1.00
251, OT4, Lautaro, Bal. Per, -0.50
252, OT4, Quiq Silv., Reb.Def, +1.00
253, OT4, Lautaro, Tiro 2, -0.50
254, OT4, Alejandro, Bal. Per, -0.50
255, OT4, Alberto, Prov.Pe, +1.00
256, OT4, Lautaro, Tiro 3, -0.50
257, OT4, Lautaro, Tiro 2, -0.50
259, OT4, Eric, Tiro 2, +2.00
260, OT4, Martin, Bal. Per, -0.50
261, OT4, Martin, Robo, +1.00
262, OT4, Quiq Pic., Can Fac, -2.00
263, OT4, Jordi, Tiro 2, +2.00
264, OT4, Jorge, Reb.Def, +1.00
""".strip()


PERIOD_TO_INT = {
    "Q1": 1,
    "Q2": 2,
    "Q3": 3,
    "Q4": 4,
    "OT": 5,
    "OT2": 6,
    "OT3": 7,
    "OT4": 8,
}


def norm(text: str) -> str:
    txt = unicodedata.normalize("NFKD", (text or "").strip().lower())
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    return "".join(ch for ch in txt if ch.isalnum())


def canonical_action_label(raw_name: str, raw_value: float) -> str:
    key = norm(raw_name)
    aliases = {
        "tiro": "Tiro 1",
        "tiro1": "Tiro 1",
        "tiro2": "Tiro 2",
        "tiro3": "Tiro 3",
        "rebof": "Reb.Of.",
        "rebdef": "Reb.Def",
        "asist": "Asist",
        "robo": "Robo",
        "balper": "Bal.Per",
        "balonperdido": "Bal.Per",
        "taprec": "Tap.Rec",
        "tapre": "Tap.Rec",
        "tapon": "Tapón",
        "provpe": "Prov.Pe",
        "canfac": "Can.Fác",
        "falta": "Falta",
    }
    mapped = aliases.get(key)
    if mapped:
        return mapped
    if key == "tiro":
        return "Tiro 1" if raw_value <= 1.0 else "Tiro 2"
    raise ValueError(f"Acción no reconocida: '{raw_name}'")


def parse_logs(raw: str) -> List[Dict]:
    rows: List[Dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 5:
            raise ValueError(f"Línea inválida (esperadas 5 columnas): {line}")
        play_no, period, player, action, value_s = parts
        try:
            no = int(play_no)
        except ValueError as exc:
            raise ValueError(f"Número de jugada inválido: {play_no}") from exc
        if period not in PERIOD_TO_INT:
            raise ValueError(f"Período inválido: {period}")
        try:
            value = float(value_s.replace("+", ""))
        except ValueError as exc:
            raise ValueError(f"Valoración inválida: {value_s}") from exc
        rows.append(
            {
                "play_no": no,
                "period_label": period,
                "period": PERIOD_TO_INT[period],
                "player_raw": player,
                "action_raw": action,
                "value": round(value, 2),
            }
        )
    rows.sort(key=lambda r: r["play_no"])
    return rows


def build_player_index(players: List[Player]) -> Dict[str, Player]:
    idx: Dict[str, Player] = {}
    for p in players:
        n = norm(p.name)
        idx[n] = p
        # alias util para abreviaturas tipo "Quiq Pic." / "Quiq Pica"
        first_two = "".join(norm(tok) for tok in p.name.split()[:2])
        if first_two:
            idx.setdefault(first_two, p)
    return idx


def resolve_player(player_index: Dict[str, Player], raw_name: str) -> Player:
    k = norm(raw_name)
    if k in player_index:
        return player_index[k]
    # fallback por prefijo (ej: "quiqpic" vs "quiqpica")
    for name_key, player in player_index.items():
        if name_key.startswith(k) or k.startswith(name_key):
            return player
    raise ValueError(f"Jugador no encontrado en el equipo: '{raw_name}'")


def build_action_index(team_id: int, user_id: int) -> Dict[Tuple[str, float], ActionDefinition]:
    idx: Dict[Tuple[str, float], ActionDefinition] = {}
    actions = get_actions_for_team(team_id, user_id)
    for a in actions:
        try:
            label = canonical_action_label(a.name, round(a.value, 2))
        except ValueError:
            # Ignorar acciones personalizadas que no forman parte del log a importar.
            continue
        key = (norm(label), round(float(a.value), 2))
        idx.setdefault(key, a)
    return idx


def resolve_action(action_index: Dict[Tuple[str, float], ActionDefinition], raw_name: str, value: float) -> ActionDefinition:
    label = canonical_action_label(raw_name, value)
    key = (norm(label), round(value, 2))
    action = action_index.get(key)
    if not action:
        raise ValueError(f"No existe acción configurada para '{raw_name}' con valoración {value:+.2f}")
    return action


def find_team(team_name: str = "", team_id: int | None = None) -> Team:
    teams = Team.query.all()
    if team_id is not None:
        team = Team.query.get(team_id)
        if not team:
            raise ValueError(f"No existe el equipo con id={team_id}")
        return team

    candidates = [t for t in teams if norm(t.name) == norm(team_name)]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        if not teams:
            raise ValueError(
                "No hay equipos en la base de datos. Crea/importa primero el equipo y sus jugadores."
            )
        available = ", ".join(sorted({t.name for t in teams}))
        raise ValueError(f"No existe el equipo '{team_name}'. Equipos disponibles: {available}")
    names = ", ".join(f"{t.id}:{t.name}" for t in candidates)
    raise ValueError(f"Hay varios equipos con nombre '{team_name}': {names}.")


def get_or_create_match(team: Team, opponent: str, match_date: datetime, replace: bool) -> Match:
    existing = [
        m
        for m in Match.query.filter_by(team_id=team.id, opponent=opponent).all()
        if m.date and m.date.date() == match_date.date()
    ]
    if existing:
        match = sorted(existing, key=lambda m: m.id)[-1]
        if match.events and not replace:
            raise ValueError(
                f"Ya existe el partido id={match.id} con {len(match.events)} eventos. "
                "Usa --replace para recargarlo."
            )
        if replace:
            MatchEvent.query.filter_by(match_id=match.id).delete()
            match.current_period = 1
            match.result_us = 0
            match.result_them = 0
        return match

    match = Match(
        opponent=opponent,
        date=match_date,
        is_home=True,
        quarters=4,
        result_us=0,
        result_them=0,
        current_period=1,
        user_id=team.user_id,
        team_id=team.id,
    )
    db.session.add(match)
    db.session.flush()
    return match


def ensure_roster_has_logged_players(match: Match, players_needed: List[Player]) -> None:
    current_ids = {p.id for p in match.roster}
    for p in players_needed:
        if p.id not in current_ids:
            match.roster.append(p)


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga el partido Infantil vs Claret con los logs proporcionados.")
    parser.add_argument("--team-id", type=int, default=None, help="ID de equipo (prioridad sobre --team)")
    parser.add_argument("--team", default=TEAM_NAME, help="Nombre del equipo (por defecto: Infantil)")
    parser.add_argument("--opponent", default=OPPONENT, help="Rival (por defecto: Claret)")
    parser.add_argument("--date", default=MATCH_DATE, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--score-us", type=int, default=EXPECTED_SCORE_US, help="Marcador propio final esperado")
    parser.add_argument("--score-them", type=int, default=EXPECTED_SCORE_THEM, help="Marcador rival final esperado")
    parser.add_argument("--replace", action="store_true", help="Reemplaza eventos si el partido ya existe")
    parser.add_argument("--dry-run", action="store_true", help="Valida sin guardar en base de datos")
    args = parser.parse_args()

    try:
        match_date = datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print("ERROR: --date debe tener formato YYYY-MM-DD", file=sys.stderr)
        return 1

    rows = parse_logs(RAW_LOGS)

    with app.app_context():
        try:
            team = find_team(team_name=args.team, team_id=args.team_id)
            player_index = build_player_index(team.players)
            action_index = build_action_index(team.id, team.user_id)

            match = get_or_create_match(team, args.opponent, match_date, args.replace)
            parsed_players: List[Player] = []
            events_to_create: List[MatchEvent] = []
            score_us_from_actions = 0

            base_ts = datetime(match_date.year, match_date.month, match_date.day, 12, 0, 0)

            for seq, row in enumerate(rows, start=1):
                player = resolve_player(player_index, row["player_raw"])
                action = resolve_action(action_index, row["action_raw"], row["value"])

                if player not in parsed_players:
                    parsed_players.append(player)

                score_us_from_actions += int(action.score_value or 0)
                events_to_create.append(
                    MatchEvent(
                        match_id=match.id,
                        player_id=player.id,
                        action_id=action.id,
                        opponent_points=0,
                        period=row["period"],
                        game_minute=0,
                        timestamp=base_ts + timedelta(seconds=seq),
                    )
                )

            ensure_roster_has_logged_players(match, parsed_players)

            for e in events_to_create:
                db.session.add(e)

            # Si se quiere reflejar marcador rival final en exportación/listado,
            # añadimos un único evento de rival al final.
            if args.score_them and args.score_them > 0:
                db.session.add(
                    MatchEvent(
                        match_id=match.id,
                        player_id=None,
                        action_id=None,
                        opponent_points=int(args.score_them),
                        period=max(r["period"] for r in rows),
                        game_minute=0,
                        timestamp=base_ts + timedelta(seconds=len(events_to_create) + 1),
                    )
                )

            match.current_period = max(r["period"] for r in rows)
            match.result_us = int(args.score_us)
            match.result_them = int(args.score_them)

            if args.dry_run:
                db.session.rollback()
                print("DRY RUN OK")
                print(f"- Equipo: {team.name} (id={team.id})")
                print(f"- Partido: {args.team} vs {args.opponent} ({args.date})")
                print(f"- Eventos jugador parseados: {len(events_to_create)}")
                print(f"- Puntos por acciones: {score_us_from_actions}")
                print(f"- Marcador esperado: {args.score_us}-{args.score_them}")
                return 0

            db.session.commit()

            print("IMPORTACION COMPLETADA")
            print(f"- Match ID: {match.id}")
            print(f"- URL tracker: /match/{match.id}")
            print(f"- URL export: /export/match/{match.id}")
            print(f"- Eventos jugador insertados: {len(events_to_create)}")
            print(f"- Puntos por acciones: {score_us_from_actions}")
            print(f"- Marcador final guardado: {args.score_us}-{args.score_them}")
            if score_us_from_actions != int(args.score_us):
                print(
                    f"AVISO: puntos por acciones ({score_us_from_actions}) != score-us ({args.score_us}).",
                    file=sys.stderr,
                )
            return 0

        except Exception as exc:
            db.session.rollback()
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
