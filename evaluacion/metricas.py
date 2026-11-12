"""Métricas de reidentificación (¿es el mismo animal?), en Python puro.

Entrada: un embedding (lista de floats) por foto, la etiqueta del animal y la especie.
Solo se comparan fotos de la MISMA especie (como hará el motor: perro con perro).

- Recall@K: para cada foto (consulta), ¿aparece otra foto del mismo animal entre las K
  más parecidas? Es lo que verá el dueño: "¿está mi mascota en las primeras K sugerencias?".
- mAP: qué tan arriba quedan, en promedio, TODAS las fotos correctas.
- Verificación por pares (mismo animal vs. distinto):
  - AUC: probabilidad de que un par "mismo animal" tenga más similitud que uno "distinto".
  - Para un umbral que deje pasar solo el 1 % / 5 % de pares distintos (falsos positivos),
    qué porcentaje de pares correctos se detecta (TPR) y la precisión.
"""
from __future__ import annotations

import math
from collections import Counter


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def similarity_matrix(embeddings: list[list[float]]) -> list[list[float]]:
    """Similitud coseno entre todas las fotos (1 = idénticas, 0 = sin relación)."""
    unit = [normalize(e) for e in embeddings]
    n = len(unit)
    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            s = sum(a * b for a, b in zip(unit[i], unit[j]))
            sim[i][j] = sim[j][i] = s
    return sim


def ranking_metrics(sim, labels, species, ks=(1, 5, 10)) -> dict:
    """Recall@K y mAP. Se omiten consultas cuyo animal no tiene otra foto."""
    hits = Counter()
    average_precisions = []
    queries = 0
    for i in range(len(labels)):
        candidates = [j for j in range(len(labels)) if j != i and species[j] == species[i]]
        relevant = {j for j in candidates if labels[j] == labels[i]}
        if not relevant:
            continue
        queries += 1
        ranked = sorted(candidates, key=lambda j: sim[i][j], reverse=True)
        first = next(pos for pos, j in enumerate(ranked, 1) if j in relevant)
        for k in ks:
            if first <= k:
                hits[k] += 1
        found, precisions = 0, []
        for pos, j in enumerate(ranked, 1):
            if j in relevant:
                found += 1
                precisions.append(found / pos)
        average_precisions.append(sum(precisions) / len(relevant))
    if not queries:
        return {"consultas": 0}
    out = {"consultas": queries, "mAP": sum(average_precisions) / queries}
    out |= {f"recall@{k}": hits[k] / queries for k in ks}
    return out


def pair_scores(sim, labels, species):
    positives, negatives = [], []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            if species[i] != species[j]:
                continue
            (positives if labels[i] == labels[j] else negatives).append(sim[i][j])
    return positives, negatives


def auc(positives: list[float], negatives: list[float]) -> float | None:
    """Área bajo la curva ROC (Mann-Whitney), con empates contados como 0,5."""
    if not positives or not negatives:
        return None
    scored = sorted([(s, 1) for s in positives] + [(s, 0) for s in negatives])
    rank_sum, i = 0.0, 0
    while i < len(scored):
        j = i
        while j < len(scored) and scored[j][0] == scored[i][0]:
            j += 1
        mean_rank = (i + 1 + j) / 2
        rank_sum += mean_rank * sum(1 for _, y in scored[i:j] if y == 1)
        i = j
    p, n = len(positives), len(negatives)
    return (rank_sum - p * (p + 1) / 2) / (p * n)


def at_false_positive_rate(positives, negatives, target_fpr: float) -> dict | None:
    """Umbral que deja pasar como máximo `target_fpr` de los pares distintos."""
    if not positives or not negatives:
        return None
    ordered = sorted(negatives, reverse=True)
    allowed = int(math.floor(target_fpr * len(ordered)))
    # Umbral: justo por encima del negativo número `allowed`+1 más alto.
    threshold = ordered[allowed] + 1e-9 if allowed < len(ordered) else min(ordered)
    tp = sum(1 for s in positives if s >= threshold)
    fp = sum(1 for s in negatives if s >= threshold)
    return {"umbral": threshold, "tpr": tp / len(positives), "fpr": fp / len(negatives),
            "precision": tp / (tp + fp) if tp + fp else None}


def evaluate(embeddings, labels, species, ks=(1, 5, 10)) -> dict:
    sim = similarity_matrix(embeddings)
    positives, negatives = pair_scores(sim, labels, species)
    return {
        "ranking": ranking_metrics(sim, labels, species, ks),
        "pares": {"mismo_animal": len(positives), "distinto_animal": len(negatives),
                  "auc": auc(positives, negatives),
                  "fpr_1%": at_false_positive_rate(positives, negatives, 0.01),
                  "fpr_5%": at_false_positive_rate(positives, negatives, 0.05)},
    }
