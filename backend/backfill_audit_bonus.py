"""
backfill_audit_bonus.py — rétro-crédite le BONUS D'AUDIT (S.AUDIT_BONUS) sur tous les
audits DÉJÀ faits avant l'introduction du bonus.

Chaque audit (source 'audit'/'challenge', déjà noté passed/failed, hors cartes no_audit)
aurait dû rapporter +AUDIT_BONUS. On ajoute donc, par (joueur, cours),
  nb_audits * AUDIT_BONUS
à son XP de la compétition correspondante.

Une seule fois : marqueur sur le volume persistant. Au 1er boot après le déploiement,
TOUS les audits existants sont "d'avant le bonus" (le code inline ne les a pas crédités) ;
les audits faits APRÈS reçoivent le bonus en direct -> aucun double comptage.
"""
import os
import db as DB
import scoring as S

MARKER = os.path.join(os.path.dirname(DB.DB_PATH) or ".", ".audit_bonus_backfill_done")


def main():
    if os.path.exists(MARKER):
        print("AUDIT_BONUS_BACKFILL: déjà fait (marqueur présent).")
        return
    DB.init_db()
    con = DB.get_db()
    with DB.LOCK:
        rows = con.execute("""
            SELECT a.user_id, c.course, COUNT(*) n
            FROM audits a JOIN cards c ON c.id = a.card_id
            WHERE a.source IN ('audit','challenge') AND a.status IN ('passed','failed')
                  AND c.no_audit = 0
            GROUP BY a.user_id, c.course
        """).fetchall()
        total = 0
        for r in rows:
            delta = round(r["n"] * S.AUDIT_BONUS, 2)
            sc = con.execute("SELECT xp, xp_milestone, tokens FROM scores WHERE user_id=? AND course=?",
                             (r["user_id"], r["course"])).fetchone()
            if sc:
                new_xp = round(sc["xp"] + delta, 2)
                granted, new_ms = S.tokens_for_xp(sc["xp_milestone"], new_xp)
                con.execute("UPDATE scores SET xp=?, xp_milestone=?, tokens=? WHERE user_id=? AND course=?",
                            (new_xp, new_ms, sc["tokens"] + granted, r["user_id"], r["course"]))
            else:
                con.execute("INSERT INTO scores(user_id, course, xp) VALUES (?,?,?)",
                            (r["user_id"], r["course"], delta))
            name = con.execute("SELECT name FROM users WHERE id=?", (r["user_id"],)).fetchone()
            print(f"  {name['name'] if name else r['user_id']} / {r['course']}: "
                  f"{r['n']} audits -> +{delta} XP")
            total += r["n"]
        con.commit()
    try:
        open(MARKER, "w").write("done")
    except Exception:
        pass
    print(f"AUDIT_BONUS_BACKFILL: {total} audits rétro-crédités (+{S.AUDIT_BONUS} chacun).")


if __name__ == "__main__":
    main()
