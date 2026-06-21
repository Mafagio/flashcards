"""del_bayes_s11.py — supprime les cartes Bayesian « Série 11 » (notebook Python, retirées)
de la base, ainsi que leurs reviews/audits. Naturellement idempotent."""
import db as DB


def main():
    DB.init_db()
    con = DB.get_db()
    with DB.LOCK:
        ids = [r["id"] for r in con.execute(
            "SELECT id FROM cards WHERE id LIKE 'bayes-s11-%'").fetchall()]
        if not ids:
            print("DEL_S11: rien à supprimer.")
            return
        ph = ",".join("?" * len(ids))
        con.execute(f"DELETE FROM audits  WHERE card_id IN ({ph})", ids)   # référencent cards (+ reviews)
        con.execute(f"DELETE FROM reviews WHERE card_id IN ({ph})", ids)
        con.execute(f"DELETE FROM cards   WHERE id IN ({ph})", ids)
        con.commit()
    print(f"DEL_S11: {len(ids)} carte(s) bayes-s11 supprimée(s).")


if __name__ == "__main__":
    main()
