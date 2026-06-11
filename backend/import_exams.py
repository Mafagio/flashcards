"""
import_exams.py — charge les examens à note déclarée (Time Series) dans la base.

⚠️  CONFIDENTIEL : ce fichier lit ts_exams.json (énoncés + corrigés + barèmes
transcrits VERBATIM des vrais examens). Ce JSON est dans .gitignore et ne doit
JAMAIS être commité : il vit côté backend uniquement (volume Railway /data).

Chaque examen :
{
  "id": "2024",                     # identifiant STABLE et unique
  "title": "Examen 2024",
  "exercises": [
    { "id": "tsx-2024-e1",          # id global unique (sert de card_id pour l'audit)
      "front": "<énoncé, LaTeX ok>",
      "back":  "<corrigé de référence>",
      "bareme": { "total": 6, "points": [ {"label": "...", "weight": 2}, ... ] },
      "difficulty": 3 }
  ]
}

Chaque exercice est aussi enregistré comme carte kind="exam" (jamais montrée en
Réviser/Progression/duels) pour réutiliser la machinerie d'audit existante.
"""

import sys, json
import db as DB


def main(path: str):
    DB.init_db()
    with open(path, encoding="utf-8") as f:
        exams = json.load(f)
    conn = DB.get_db()
    ne = nx = 0
    with DB.LOCK:
        for e in exams:
            exos = e["exercises"]
            conn.execute("""
                INSERT INTO ts_exams(id, title, n_exercises, payload_json)
                VALUES (:id,:title,:n,:payload)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, n_exercises=excluded.n_exercises,
                    payload_json=excluded.payload_json
            """, {"id": e["id"], "title": e["title"], "n": len(exos),
                  "payload": json.dumps(exos, ensure_ascii=False)})
            ne += 1
            for x in exos:
                conn.execute("""
                    INSERT INTO cards(id, course, category, kind, front, back, bareme_json, difficulty)
                    VALUES (:id,:course,:category,'exam',:front,:back,:bareme,:difficulty)
                    ON CONFLICT(id) DO UPDATE SET
                        course=excluded.course, category=excluded.category, kind=excluded.kind,
                        front=excluded.front, back=excluded.back,
                        bareme_json=excluded.bareme_json, difficulty=excluded.difficulty
                """, {"id": x["id"], "course": "Time Series", "category": e["title"],
                      "front": x["front"], "back": x["back"],
                      "bareme": json.dumps(x.get("bareme", {"total": 6, "points": []}), ensure_ascii=False),
                      "difficulty": int(x.get("difficulty", 3))})
                nx += 1
        conn.commit()
    print(f"{ne} examens / {nx} exercices importés (backend only) dans {DB.DB_PATH}.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ts_exams.json")
