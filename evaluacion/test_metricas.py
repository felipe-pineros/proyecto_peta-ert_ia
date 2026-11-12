"""Pruebas de las métricas con datos inventados cuyo resultado se conoce de antemano."""
import pytest

from metricas import at_false_positive_rate, auc, evaluate


LABELS = ["toby", "toby", "luna", "luna", "michi", "michi"]
SPECIES = ["dog", "dog", "dog", "dog", "cat", "cat"]


def test_separacion_perfecta():
    # Cada animal apunta en una dirección distinta: el modelo "perfecto".
    emb = [[1, 0, 0], [0.99, 0.01, 0], [0, 1, 0], [0.01, 0.99, 0], [0, 0, 1], [0, 0.01, 0.99]]
    r = evaluate(emb, LABELS, SPECIES)
    assert r["ranking"]["recall@1"] == 1.0 and r["ranking"]["mAP"] == 1.0
    assert r["ranking"]["consultas"] == 6
    assert r["pares"]["auc"] == 1.0
    # Solo se comparan pares de la misma especie: 2 positivos de perro + 1 de gato; 4 negativos (perros).
    assert r["pares"]["mismo_animal"] == 3 and r["pares"]["distinto_animal"] == 4


def test_modelo_que_confunde():
    # Toby se parece más a Luna que a sí mismo.
    emb = [[1, 0], [0, 1], [0.9, 0.1], [0.1, 0.9], [1, 0], [1, 0]]
    r = evaluate(emb, LABELS, SPECIES)
    assert r["ranking"]["recall@1"] < 1.0
    assert r["ranking"]["recall@5"] == 1.0  # con 3 candidatos, siempre aparece entre los 5 primeros


def test_auc_y_umbral():
    assert auc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert auc([0.1], [0.9]) == 0.0
    assert auc([0.5], [0.5]) == 0.5
    r = at_false_positive_rate([0.9, 0.8, 0.3], [0.5, 0.2, 0.1, 0.05], 0.0)
    assert r["fpr"] == 0.0 and r["tpr"] == pytest.approx(2 / 3) and r["precision"] == 1.0


def test_animal_con_una_sola_foto_no_es_consulta():
    r = evaluate([[1, 0], [0, 1], [0.9, 0.1]], ["a", "b", "a"], ["dog"] * 3)
    assert r["ranking"]["consultas"] == 2  # "b" solo sirve como distractor
