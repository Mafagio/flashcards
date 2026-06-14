"""dedup_pending_audits.py — supprime les audits source='audit' EN ATTENTE en double sur la
même carte (même utilisateur), séquelle d'avant la dédup du tirage. Un audit en attente n'a
AUCUNE XP appliquée (l'XP l'est à la correction) -> suppression sûre. Naturellement idempotent
(une fois dédupliqué, plus rien à faire aux boots suivants)."""
import db as DB


def main():
    DB.init_db()
    con = DB.get_db()
    with DB.LOCK:
        dups = con.execute("""
            SELECT user_id, card_id, MIN(id) AS keep, COUNT(*) AS n
            FROM audits WHERE status='pending' AND source='audit'
            GROUP BY user_id, card_id HAVING COUNT(*) > 1
        """).fetchall()
        removed = 0
        for d in dups:
            extra = con.execute(
                "SELECT id, review_id FROM audits WHERE status='pending' AND source='audit' "
                "AND user_id=? AND card_id=? AND id<>?",
                (d["user_id"], d["card_id"], d["keep"])).fetchall()
            for a in extra:
                if a["review_id"]:
                    con.execute("UPDATE reviews SET status='cleared' WHERE id=?", (a["review_id"],))
                con.execute("DELETE FROM audits WHERE id=?", (a["id"],))
                removed += 1
        con.commit()
    print(f"DEDUP_PENDING: {removed} audit(s) en attente en double supprimé(s).")


if __name__ == "__main__":
    main()
