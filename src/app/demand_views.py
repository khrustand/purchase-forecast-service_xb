"""Показ неопределенности спроса и цены резерва без ложной точности."""

from html import escape


def number(value, places=1):
    return f'{value:.{places}f}' if value is not None else '—'


def model_details(model: dict, expiry: bool = True) -> str:
    if not model or model.get('expected_demand') is None:
        return '<p>Спрос не установлен; для тестовой позиции объем задан отдельно. Вероятности и прибыль не рассчитаны.</p>'
    remaining = 'Остаток с риском истечения срока' if expiry else 'Остаток к следующей поставке; это еще не списание'
    scenarios = ''.join(f"<tr><td>Спрос +{row['demand_uplift_percent']}%</td><td>{number(row['expected_remaining'])}</td>"
                        f"<td>{number(row['expected_shortage'])}</td><td>{number(100 * row['stockout_probability'])}%</td></tr>"
                        for row in model['sensitivity'])
    return f'''<section><h3>Спрос и резерв по модели</h3><dl>
    <dt>Средний гостевой спрос</dt><dd>{number(model['expected_demand'])} порц.</dd>
    <dt>Для гостей с резервом</dt><dd>{model['guest_quantity']} порц., резерв сверх округленного среднего {model['reserve']}</dd>
    <dt>Экономический объем при нулевой ценности остатка в конце окна</dt><dd>{model['economic_quantity'] if model['economic_quantity'] is not None else 'нет подтвержденной себестоимости'} порц. гостям</dd>
    <dt>Цена защиты спроса против экономического объема</dt><dd>{number(model['availability_cost'], 2)} ₽ ожидаемой прибыли</dd>
    <dt>Ориентир наличия достигнут в модели</dt><dd>{'да' if model.get('service_target_met') else 'нет: резерв ограничен ценой потерь'}</dd>
    <dt>{remaining}</dt><dd>{number(model['expected_remaining'])} порц.</dd>
    <dt>Неудовлетворенный спрос</dt><dd>{number(model['expected_shortage'])} порц.; риск за весь период {number(model['stockout_probability'] * 100)}%</dd>
    <dt>Стоимость остатка под риском</dt><dd>{number(model['expected_remaining_cost'], 2)} ₽</dd>
    <dt>Упущенный вклад в прибыль при нехватке</dt><dd>{number(model['expected_lost_margin'], 2)} ₽</dd>
    <dt>Модельный результат после себестоимости всего выпуска и питания</dt><dd>{number(model['expected_profit'], 2)} ₽, без аренды и зарплаты</dd>
    <dt>История</dt><dd>{model['history_points']} наблюдений; {escape(model['basis'])}</dd></dl>
    <p>Проверка потенциального спроса при неизменном плане; прибавки ниже — предположения, не установленный факт.</p>
    <table><thead><tr><th>Предположение</th><th>Остаток</th><th>Недопродано</th><th>Риск нехватки</th></tr></thead><tbody>{scenarios}</tbody></table></section>'''


def render_demand_method(strategy: dict, view: str) -> str:
    settings = strategy.get('demand_model', {})
    if not settings:
        return ''
    level = settings['service_level'] * 100
    route = '/production' if view == 'production' else ('/analytics' if view == 'analytics' else '/')
    period = strategy['future_orders'][0]
    models = [row['model'] for row in period['rows'] if row.get('model')]
    models += [row['model'] for day in strategy['production_days'] if period['start'] <= day['date'] <= period['end'] for row in day['rows']]
    known = [model for model in models if model.get('expected_demand') is not None]
    priced = [model for model in known if model.get('expected_profit') is not None]
    rows = []
    policies = []
    for policy, label in [('economic', 'Экономический'), ('balanced', 'Сбалансированный — в плане'), ('availability', 'Повышенное наличие')]:
        selected = [next((row for row in model.get('alternatives', []) if row['policy'] == policy), model)
                    if policy != 'balanced' else model for model in models]
        quantity = sum(row['quantity'] or 0 for row in selected)
        remaining = sum(row.get('expected_remaining') or 0 for row in selected)
        shortage = sum(row.get('expected_shortage') or 0 for row in selected)
        result = sum(row.get('expected_profit') or 0 for row in selected)
        policies.append(f'<tr><td>{label}</td><td>{quantity}</td><td>{remaining:.1f}</td><td>{shortage:.1f}</td><td>{result:.2f}</td></tr>')
    for percent in (0, 10, 20):
        selected = known if percent == 0 else [next(r for r in model['sensitivity'] if r['demand_uplift_percent'] == percent) for model in known]
        remaining = sum(row['expected_remaining'] for row in selected)
        shortage = sum(row['expected_shortage'] for row in selected)
        risk_cost = sum(row['expected_remaining_cost'] for row in selected if row['expected_remaining_cost'] is not None)
        lost_margin = sum(row['expected_lost_margin'] for row in selected if row['expected_lost_margin'] is not None)
        rows.append(f"<tr><td>{'По наблюдаемым продажам' if percent == 0 else f'Если спрос выше на {percent}%'}</td>"
                    f"<td>{remaining:.1f}</td><td>{shortage:.1f}</td><td>{risk_cost:.2f}</td><td>{lost_margin:.2f}</td></tr>")
    return f'''<section class="calculation-box" id="demand"><h3>Единый метод для всей кулинарии</h3>
    <form method="get" action="{route}"><input type="hidden" name="start" value="{strategy['production_days'][0]['date']}"><label>Защита спроса по модели, % <input type="number" min="1" max="99" step="1" name="service" value="{level:.0f}" required></label>
    <label>Цена резерва, % модельного результата блюда <input type="number" min="0" max="100" step="1" name="reserve_cost" value="{settings.get('profit_tolerance', .05) * 100:.0f}" required></label>
    <button type="submit">Пересчитать</button></form>
    <p>Стартовая настройка {level:.0f}% — желаемая обеспеченность спроса по модели, не измеренная доступность на витрине.
    Стремимся к этому наличию, но ограничиваем цену резерва {settings.get('profit_tolerance', .05) * 100:.0f}% положительного модельного результата блюда.
    Это пробные настройки, не установленный оптимум. Если запас слишком дорог, ориентир наличия не достигается — это видно в деталях.
    Резерв зависит от разброса продаж,
    а не от общей надбавки ко всем блюдам. Партии ТТ и минимум 3 для обычной поставки сейчас не применяются.
    Тесты без истории остаются по 3 порции. Питание добавляется один раз.</p>
    <p>До 8 недавних сопоставимых окон, последние наблюдения имеют больший вес. Чеки и погода применяются один раз.
    Нулевой риск в этой небольшой выборке не гарантирует отсутствия нехватки в будущем.
    Продажи ограничены наличием: времени окончания блюд в источниках нет, поэтому скрытый спрос не восстановлен.
    Отсутствующие дни не считаются нулевыми. Часы утреннего спроса и переход гостей между блюдами пока не оценены.</p>
    <p>Ближайший период {period['start']}—{period['end']}, поставка и ТТ вместе. Прогноз риска есть для {len(known)} из {len(models)} расчетов,
    себестоимость для {len(priced)}. Суммы в рублях ниже относятся только к позициям с известной себестоимостью.</p>
    <h3>Сравнение подходов на одном прогнозе</h3><div class="table-wrap"><table><thead><tr><th>Подход</th><th>План, порц.</th>
    <th>Остаток</th><th>Неудовлетворенный спрос</th><th>Модельный результат, ₽</th></tr></thead><tbody>{''.join(policies)}</tbody></table></div>
    <p>Где себестоимость неизвестна, экономический вариант не определен: в сравнении сохранен тот же объем защиты спроса.
    Пробные позиции включены в количества, но их прибыль и риск не выдумываются.</p>
    <div class="table-wrap"><table><thead><tr><th>Сценарий при том же плане</th><th>Ожидаемый остаток, порц.</th><th>Неудовлетворенный спрос, порц.</th>
    <th>Стоимость остатка под риском, ₽</th><th>Упущенный вклад, ₽</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
    <p>Остаток к следующей поставке не всегда истекает в этот день; его стоимость не является прогнозом фактического списания.
    В экономической оценке его дальнейшая ценность пока принята за ноль — это консервативное упрощение,
    особенно для трехдневных блюд в двухдневном окне. Фактические остатки перед заказом здесь не вычитаются.
    ТТ и двухдневные пятничные блюда оцениваются до конца срока. Дневные числа для одной поставки — распределение общего объема,
    не отдельные поставки. Неудовлетворенные порции нельзя приравнять к потерянным гостям: часть выберет другое блюдо.</p>
    <p>Общая цель 2% остается отдельным контролем фактических потерь. Модель не обещает ее достижения и не выдает
    условные сценарии +10/+20% за подтвержденный рост спроса. <a href="https://ocw.mit.edu/courses/15-772j-d-lab-supply-chains-fall-2014/6952be57b43aa185119c6f114908bcc5_MIT15_772JF14_Newsboy.pdf">Экономическая основа метода</a>.</p></section>'''
