"""
scoring.py — Le cœur "intelligent" du jeu Battle.

Tout est dans des fonctions PURES (pas d'effet de bord, pas de DB) pour que la
logique soit lisible, testable, et facile à régler. Lance `python scoring.py`
pour voir la table des points et vérifier les propriétés.

Idée centrale (le problème d'honnêteté) :
  En mode "Réviser" tu cliques "je connais", et rien ne prouve que c'est vrai.
  C'est du *cheap talk*. On le rend non rentable EN ESPÉRANCE :
    - toutes les AUDIT_BATCH cartes "connues", AUDIT_SAMPLE sont tirées au sort
      en test écrit obligatoire (proba d'audit p = SAMPLE / BATCH) ;
    - une carte auditée est notée /6 par un correcteur (LLM) ;
    - tu déclares en plus un NIVEAU DE CONFIANCE q ; le gain à l'audit suit une
      règle de score PROPRE (Brier) -> ton espérance est maximale quand tu
      déclares ta VRAIE proba de réussir. Bluffer une confiance haute brûle.

On veut RÉCOMPENSER LE GRIND : chaque carte travaillée donne des points de base
tout de suite (dopamine + progression linéaire). Les audits ne servent qu'à
garder ce grind HONNÊTE et à laisser la maîtrise réelle creuser l'écart.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# PARAMÈTRES — règle tout ici.
# ---------------------------------------------------------------------------

BASE_KNOWN: float = 1.0      # XP immédiat pour une carte marquée "connue"
BASE_UNKNOWN: float = 0.3    # XP immédiat pour un honnête "pas connue" (revient)

AUDIT_BATCH: int = 20        # toutes les 20 cartes "connues"...
AUDIT_SAMPLE: int = 4        # ...4 sont tirées au sort en audit (test écrit)

MASTERY_W: float = 10.0      # échelle de la règle de score propre (Brier)
PASS_SCORE: int = 4          # note /6 à partir de laquelle l'audit est "réussi"
MAX_SCORE: int = 6

# Niveaux de confiance déclarables (touches 2 / 3 / 4 en révision).
CONF_LEVELS: list[float] = [0.60, 0.80, 0.95]

TOKEN_EVERY: float = 50.0    # 1 jeton "challenge" par 50 XP de RECORD personnel
CHALLENGE_BOUNTY: float = 5.0   # gain du challenger si l'adversaire RATE
CHALLENGE_DEFENSE: float = 3.0  # gain du défenseur s'il RÉUSSIT le challenge

DUEL_WIN: float = 10.0
DUEL_PARTICIPATE: float = 2.0
DUEL_N: int = 6              # nb de cartes par duel

# Pondération du tirage d'audit (audit plus probable si jamais audité / dur /
# raté récemment par l'adversaire) -> l'audit devient informatif, pas du bruit.
W_NEVER_AUDITED = 1.6
W_DIFFICULTY = {1: 0.8, 2: 1.0, 3: 1.4}
W_OPP_FAILED = 1.5


# ---------------------------------------------------------------------------
# FONCTIONS PURES
# ---------------------------------------------------------------------------

def outcome_from_score(score: int) -> int:
    """1 si l'audit est réussi (note >= PASS_SCORE), 0 sinon."""
    return 1 if score >= PASS_SCORE else 0


def mastery_points(q: float, outcome: int) -> float:
    """
    Points de MAÎTRISE gagnés/perdus à un audit, via une règle de score propre.

        m(q, o) = W * [ (o - 0.5)^2 - (o - q)^2 ]

    - Le terme -(o - q)^2 est le score de Brier (négatif de) : c'est une règle
      STRICTEMENT PROPRE, donc E[m | vraie proba p] est maximisée en q = p.
      Déclarer sa vraie croyance est la stratégie optimale.
    - On recentre par +(o - 0.5)^2 (constante en q -> properté préservée) pour
      que q = 0.5 donne EXACTEMENT 0 : "je ne sais pas" = aucun pari, 0 risque /
      0 gain.

    Effet : confiance haute + correct = joli + ; confiance haute + faux = grosse
    pénalité (c'est ça qui rend le bluff non rentable). Voir la table en bas.
    """
    return MASTERY_W * ((outcome - 0.5) ** 2 - (outcome - q) ** 2)


def tokens_for_xp(old_milestone: float, new_xp: float) -> tuple[int, float]:
    """
    Jetons "challenge" gagnés en franchissant de nouveaux paliers TOKEN_EVERY.

    On utilise un RECORD personnel (high-water mark) : les jetons ne sont
    accordés que pour des paliers jamais atteints. Impossible de farmer en
    faisant osciller son XP (perdre puis regagner les mêmes points).

    Retour : (jetons_accordés, nouveau_record).
    """
    if new_xp <= old_milestone:
        return 0, old_milestone
    granted = int(new_xp // TOKEN_EVERY) - int(old_milestone // TOKEN_EVERY)
    return max(0, granted), new_xp


def audit_weight(difficulty: int, never_audited: bool, opp_failed: bool) -> float:
    """Poids d'une carte dans le tirage au sort des audits (>0)."""
    w = 1.0
    if never_audited:
        w *= W_NEVER_AUDITED
    w *= W_DIFFICULTY.get(difficulty, 1.0)
    if opp_failed:
        w *= W_OPP_FAILED
    return w


def expected_mastery(q: float, p_true: float) -> float:
    """E[mastery] si on déclare q alors que la vraie proba de réussir est p_true."""
    return p_true * mastery_points(q, 1) + (1 - p_true) * mastery_points(q, 0)


# ---------------------------------------------------------------------------
# AUTO-TEST / DÉMO : `python scoring.py`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    p = AUDIT_SAMPLE / AUDIT_BATCH
    print(f"Proba d'audit par carte 'connue' : p = {AUDIT_SAMPLE}/{AUDIT_BATCH} = {p:.0%}\n")

    print("Points de maîtrise à un audit  m(q, o) :")
    print(f"{'q':>6} | {'réussi (o=1)':>13} | {'raté (o=0)':>11}")
    print("-" * 36)
    for q in CONF_LEVELS:
        print(f"{q:>6.2f} | {mastery_points(q,1):>13.2f} | {mastery_points(q,0):>11.2f}")
    print(f"{0.50:>6.2f} | {mastery_points(0.5,1):>13.2f} | {mastery_points(0.5,0):>11.2f}  (no-pari)\n")

    print("Vérif properté : pour chaque vraie proba p, le meilleur q déclarable")
    print("doit être le plus proche de p (à la grille près).")
    grid = CONF_LEVELS + [0.5]
    for p_true in [0.5, 0.6, 0.7, 0.8, 0.9, 0.99]:
        best_q = max(grid, key=lambda q: expected_mastery(q, p_true))
        print(f"  p={p_true:>4.2f}  ->  q* = {best_q:.2f}   "
              f"(E={expected_mastery(best_q, p_true):+.2f})")

    print("\nGrind honnête vs bluff (100 cartes 'connues', base +1 chacune) :")
    honest = 100 * BASE_KNOWN + (AUDIT_BATCH and 100 * p) * mastery_points(0.95, 1) / 1
    # ~ 100 base + (20 audits) * +2.48
    n_audits = round(100 * p)
    honest_xp = 100 * BASE_KNOWN + n_audits * mastery_points(0.95, 1)
    bluff_xp = 100 * BASE_KNOWN + n_audits * mastery_points(0.95, 0)
    print(f"  connaît vraiment, déclare q=0.95 : ~{honest_xp:+.0f} XP")
    print(f"  bluffe q=0.95 (rate les audits) : ~{bluff_xp:+.0f} XP")
    print(f"  -> écart honnêteté : {honest_xp - bluff_xp:+.0f} XP sur 100 cartes")

    print(f"\nJetons : 1 par {TOKEN_EVERY:.0f} XP (record perso). "
          f"Ex. passer de 0 à 170 XP -> {tokens_for_xp(0,170)[0]} jetons.")
