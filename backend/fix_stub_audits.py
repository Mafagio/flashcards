"""
fix_stub_audits.py — corrige une bonne fois les audits notés 0/6 (souvent à tort par le
correcteur « stub » quand le vrai correcteur n'avait pas tourné), et SUPPRIME du fil les
notifications « 0/6 (raté …) » correspondantes.

Au boot, UNE seule fois (marqueur sur le volume) :
  - pour chaque audit source='audit' échoué à 0/6 (avec une réponse stockée), on RE-CORRIGE
    avec le correcteur (réparé) : s'il répond pour de vrai, on applique le vrai score et on
    ajuste l'XP ; sinon (toujours pas de vrai correcteur) on retire la pénalité et on remet
    l'audit en attente ;
  - on efface les évènements de fil « … 0/6 (raté … XP) ».

Une seule fois (marqueur) : ne re-traite pas les vrais 0/6 futurs aux redémarrages suivants.
"""
import os
import json
import db as DB
import scoring as S
from grader import grade

MARKER = os.path.join(os.path.dirname(DB.DB_PATH) or ".", ".audit_zero_recheck_done")


def _adjust_xp(con, uid, course, delta):
    sc = con.execute("SELECT xp, xp_milestone, tokens FROM scores WHERE user_id=? AND course=?",
                     (uid, course)).fetchone()
    if sc:
        new_xp = round(sc["xp"] + delta, 2)
        granted, new_ms = S.tokens_for_xp(sc["xp_milestone"], new_xp)
        con.execute("UPDATE scores SET xp=?, xp_milestone=?, tokens=? WHERE user_id=? AND course=?",
                    (new_xp, new_ms, sc["tokens"] + granted, uid, course))
    elif delta:
        con.execute("INSERT INTO scores(user_id, course, xp) VALUES (?,?,?)", (uid, course, delta))


def main():
    if os.path.exists(MARKER):
        print("STUB_AUDIT_FIX: déjà fait (marqueur présent).")
        return
    DB.init_db()
    con = DB.get_db()
    rows = con.execute("""
        SELECT a.id, a.user_id, a.q, a.mastery, a.answer, c.course,
               c.front, c.back, c.bareme_json
        FROM audits a JOIN cards c ON c.id = a.card_id
        WHERE a.status='failed' AND a.score=0 AND a.source='audit'
        LIMIT 60
    """).fetchall()

    # 1) re-correction (appels API HORS verrou)
    graded = []
    for a in rows:
        if not (a["answer"] or "").strip():
            graded.append((a, {"stub": True})); continue
        try:
            res = grade(a["front"], a["back"], json.loads(a["bareme_json"]), a["answer"])
        except Exception:
            res = {"stub": True}
        graded.append((a, res))

    # 2) application (sous verrou) + purge du fil
    regraded = refunded = 0
    with DB.LOCK:
        for a, res in graded:
            old_gain = round((a["mastery"] or 0) + S.AUDIT_BONUS, 2)   # XP nette appliquée par le 0/6
            if res.get("stub"):
                _adjust_xp(con, a["user_id"], a["course"], -old_gain)  # retire la pénalité
                con.execute("UPDATE audits SET status='pending', score=NULL, justification=NULL, "
                            "mastery=0, graded_at=NULL WHERE id=?", (a["id"],))
                refunded += 1
            else:
                outcome = S.outcome_from_score(res["score"])
                new_mastery = round(S.mastery_points(a["q"], outcome), 2)
                new_gain = round(new_mastery + S.AUDIT_BONUS, 2)
                _adjust_xp(con, a["user_id"], a["course"], round(new_gain - old_gain, 2))
                con.execute("UPDATE audits SET status=?, score=?, justification=?, mastery=? WHERE id=?",
                            ("passed" if outcome else "failed", res["score"],
                             str(res.get("justification", "")), new_mastery, a["id"]))
                regraded += 1
        # purge les notifications « 0/6 (raté … » du fil (une seule fois)
        cur = con.execute("DELETE FROM events WHERE type='graded' AND text LIKE '%0/6 (raté%'")
        events_del = cur.rowcount or 0
        con.commit()
    try:
        open(MARKER, "w").write("done")
    except Exception:
        pass
    print(f"STUB_AUDIT_FIX: {regraded} 0/6 re-corrigé(s), {refunded} pénalité(s) retirée(s), "
          f"{events_del} notification(s) « 0/6 raté » supprimée(s).")


if __name__ == "__main__":
    main()
