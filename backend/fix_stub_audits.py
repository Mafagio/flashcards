"""
fix_stub_audits.py — répare les audits notés à tort par le correcteur « stub » alors que
le correcteur LLM était indisponible (justification « correcteur indisponible »).

Pour chaque tel audit (source='audit'), on RE-CORRIGE la réponse stockée avec le correcteur
(réparé) :
  - s'il répond -> on ajuste l'XP du score stub (souvent 0) vers le vrai score, et on met
    à jour l'audit (status/score/justification/mastery) ;
  - s'il est ENCORE indisponible -> on retire simplement la pénalité injuste et on remet
    l'audit en attente (l'utilisateur le refera, sans rien avoir perdu).

Idempotent : une fois re-corrigé (ou remis en attente), la justification ne contient plus
« correcteur indisponible » -> l'audit n'est plus re-traité.
"""
import json
import db as DB
import scoring as S
from grader import grade


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
    DB.init_db()
    con = DB.get_db()
    rows = con.execute("""
        SELECT a.id, a.user_id, a.q, a.mastery, a.answer, c.course,
               c.front, c.back, c.bareme_json
        FROM audits a JOIN cards c ON c.id = a.card_id
        WHERE a.justification LIKE '%correcteur indisponible%'
              AND a.status IN ('passed','failed') AND a.source='audit'
        LIMIT 30
    """).fetchall()

    # 1) re-correction (appels API HORS verrou)
    graded = []
    for a in rows:
        if not (a["answer"] or "").strip():
            graded.append((a, None)); continue
        try:
            res = grade(a["front"], a["back"], json.loads(a["bareme_json"]), a["answer"])
        except Exception:
            res = {"unavailable": True}
        graded.append((a, res))

    # 2) application en base (sous verrou)
    regraded = refunded = 0
    with DB.LOCK:
        for a, res in graded:
            old_gain = round((a["mastery"] or 0) + S.AUDIT_BONUS, 2)   # XP nette qu'avait appliquée le stub
            if res is None or res.get("unavailable"):
                # toujours indisponible -> on enlève la pénalité injuste et on remet en attente
                _adjust_xp(con, a["user_id"], a["course"], -old_gain)
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
        con.commit()
    print(f"STUB_AUDIT_FIX: {regraded} audit(s) re-corrigé(s), {refunded} pénalité(s) retirée(s) "
          f"(correcteur encore indisponible).")


if __name__ == "__main__":
    main()
