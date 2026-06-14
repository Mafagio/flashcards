"""grant_makeup_audit.py — accorde UNE seule fois à Matteo un audit de COMPENSATION pour le
doublon retiré par la dédup. Un audit en attente = une occasion d'XP (il faudra rédiger la
preuve, ce n'est PAS de l'XP gratuite). On choisit une carte Martingales qu'il a déclarée
connue, PAS déjà en attente, de préférence jamais auditée. Marqueur -> ne s'exécute qu'une fois."""
import os
import db as DB

USER = "Matteo"
COURSE = "Martingales"
MARKER = os.path.join(os.path.dirname(DB.DB_PATH) or ".", ".makeup_audit_done")


def main():
    if os.path.exists(MARKER):
        print("MAKEUP_AUDIT: déjà fait (marqueur présent).")
        return
    DB.init_db()
    con = DB.get_db()
    with DB.LOCK:
        u = con.execute("SELECT id FROM users WHERE name=?", (USER,)).fetchone()
        if not u:
            print(f"MAKEUP_AUDIT: utilisateur {USER} introuvable — rien fait.")
            return
        uid = u["id"]
        # cartes déjà en attente d'audit (toutes sources) -> à exclure (pas de doublon).
        pending = {x["card_id"] for x in con.execute(
            "SELECT DISTINCT card_id FROM audits WHERE user_id=? AND status='pending'",
            (uid,)).fetchall()}
        # reviews 'connues' clearées du cours, carte auditable, + nb d'audits déjà passés sur la carte.
        rows = con.execute("""
            SELECT r.id AS review_id, r.card_id, r.q,
                   (SELECT COUNT(*) FROM audits a WHERE a.user_id=r.user_id AND a.card_id=r.card_id) AS n_aud
            FROM reviews r JOIN cards c ON c.id=r.card_id
            WHERE r.user_id=? AND r.known=1 AND r.status IN ('cleared','provisional')
              AND c.course=? AND c.no_audit=0
            ORDER BY r.id DESC
        """, (uid, COURSE)).fetchall()
        seen, cand = set(), []
        for r in rows:
            if r["card_id"] in pending or r["card_id"] in seen:
                continue
            seen.add(r["card_id"]); cand.append(r)
        if not cand:
            print("MAKEUP_AUDIT: aucune carte éligible (toutes déjà en attente ?) — rien fait.")
            return
        cand.sort(key=lambda r: (r["n_aud"] != 0,))   # jamais auditée d'abord (tri stable)
        pick = cand[0]
        q = pick["q"] if pick["q"] else 0.80
        con.execute("INSERT INTO audits(user_id,card_id,review_id,q,source,status) "
                    "VALUES (?,?,?,?, 'audit','pending')", (uid, pick["card_id"], pick["review_id"], q))
        con.execute("UPDATE reviews SET status='audit_pending' WHERE id=?", (pick["review_id"],))
        DB.log_event(con, uid, "audit",
                     f"🎁 Audit de compensation accordé à {USER} (pour le doublon retiré).")
        con.commit()
        try:
            open(MARKER, "w").write("done")
        except Exception:
            pass
        print(f"MAKEUP_AUDIT: 1 audit accordé à {USER} sur {pick['card_id']} (q={q}).")


if __name__ == "__main__":
    main()
