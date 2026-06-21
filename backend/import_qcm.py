"""import_qcm.py — importe (upsert) les QCM d'un fichier JSON dans la table `qcm`.

Usage: python import_qcm.py qcm.bayesian.json
Idempotent : INSERT OR REPLACE par id (les réponses des joueurs, dans qcm_answers,
sont conservées car elles ne référencent que l'id du QCM)."""
import json
import sys
import db as DB


def main(path: str = "qcm.bayesian.json"):
    DB.init_db()
    con = DB.get_db()
    items = json.load(open(path, encoding="utf-8"))
    with DB.LOCK:
        for q in items:
            con.execute(
                "INSERT OR REPLACE INTO qcm(id, course, set_no, area, stem, options_json, "
                "correct_index, solution, difficulty) VALUES (?,?,?,?,?,?,?,?,?)",
                (q["id"], q["course"], int(q["set_no"]), q["area"], q["stem"],
                 json.dumps(q["options"], ensure_ascii=False), int(q["correct_index"]),
                 q["solution"], int(q.get("difficulty", 2))),
            )
        con.commit()
    n = con.execute("SELECT COUNT(*) c FROM qcm").fetchone()["c"]
    print(f"{len(items)} QCM importés depuis {path} ({n} au total dans {DB.DB_PATH}).")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "qcm.bayesian.json")
