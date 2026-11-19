"""Ранжирование ассортимента по результату после известных потерь."""

from typing import Any


def rank_profit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [row for row in rows if row.get('sold', 0) > 0
                and row.get('profit_after_known_costs', 0) > 0
                and row.get('revenue', 0) > row.get('gross_profit', 0)]
    max_profit = max((row['profit_after_known_costs'] for row in eligible), default=1)
    max_unit = max((row['profit_after_known_costs'] / row['sold'] for row in eligible), default=1)
    max_sales = max((row['sold'] for row in eligible), default=1)
    scored = []
    for row in eligible:
        unit = row['profit_after_known_costs'] / row['sold']
        score = (.5 * row['profit_after_known_costs'] / max_profit
                 + .3 * unit / max_unit + .2 * row['sold'] / max_sales)
        scored.append({**row, 'profit_per_sale': round(unit, 2), 'matrix_score': round(score, 6)})
    return sorted(scored, key=lambda row: (-row['matrix_score'], row['name']))


def propose_matrix(candidates: list[dict], economics: list[dict], capacity: int = 32) -> dict:
    active = {row['key']: row for row in candidates if row.get('active', True) and not row.get('own_production', False)}
    stats = {row['key']: row for row in economics if row['key'] in active}
    ranked = rank_profit_rows(list(stats.values()))
    selected = []
    for index,row in enumerate(ranked[:capacity - 3]):
        selected.append({**row, **active[row['key']],
                         'role': 'core' if index < capacity - 10 else 'rotation'})
    used = {row['key'] for row in selected}
    unknown = sorted((row for key,row in active.items() if key not in stats
                      or (stats[key].get('sold', 0) == 0 and stats[key].get('waste_cost', 0) == 0)),
                     key=lambda row: (row.get('test_priority', 100), row['name']))
    for row in unknown[:min(3, capacity - len(selected))]:
        selected.append({**row, 'role': 'experiment', 'matrix_score': None,
                         'profit_after_known_costs': None, 'margin_after_known_costs': None,
                         'sold': None, 'profit_per_sale': None})
        used.add(row['key'])
    excluded = [row for row in stats.values() if row['key'] not in used]
    return {'capacity': capacity, 'rows': selected, 'vacancies': capacity - len(selected),
            'core_count': sum(row['role'] == 'core' for row in selected),
            'rotation_count': sum(row['role'] == 'rotation' for row in selected),
            'experiment_count': sum(row['role'] == 'experiment' for row in selected),
            'deprioritized': sorted(excluded, key=lambda row: row.get('profit_after_known_costs', 0)),
            'notice': 'Предложение, без автоматического изменения рабочего меню. Ранжирование: 50% вклад в прибыль после известных затрат, 30% такая прибыль на проданную порцию, 20% продажи. Акты неполные; тестовые блюда еще не имеют подтвержденной маржи.'}
