"""Представление экономики ассортимента и истории покупательского потока."""

from html import escape


def render_loss_kpi(kpi: dict) -> str:
    if not kpi:
        return ''
    percent = f"{kpi['known_percent']:.2f}%" if kpi.get('known_percent') is not None else 'нет выручки'
    budget = kpi.get('budget', {})
    rows = ''.join(f"<tr><td>{row['label']}</td><td>{row['revenue']:.2f}</td>"
                   f"<td>{row['target_cost'] if row['target_cost'] is not None else '—'}</td>"
                   f"<td>{row['target_on_group_revenue_percent'] if row['target_on_group_revenue_percent'] is not None else '—'}</td>"
                   f"<td>{row['known_waste_cost'] if row['waste_days'] else 'нет актов'}</td>"
                   f"<td>{row['waste_days']}</td></tr>" for row in budget.get('rows', []))
    return f'''<section class="calculation-box" id="losses"><h3>Общий таргет — 2% выручки пекарни</h3>
    <p>Кулинария + снеки + выпечка + кондитерка + хлеб, без питания сотрудников.
    Общий бюджет потерь за {kpi['start']}—{kpi['end']}: <strong>{budget.get('total_budget', 0):,.2f} ₽</strong>.</p>
    <p>Известная себестоимость списанной кулинарии
    <strong>{kpi['known_waste_cost']:,.2f} ₽</strong> / общая выручка пекарни
    <strong>{kpi['total_revenue']:,.2f} ₽</strong> = <strong>{percent}</strong> вклада кулинарии.
    Это не общий результат пекарни и не сравнение с отдельным лимитом кулинарии 2%.</p>
    <p>Предварительный показатель: подробные акты за {kpi['waste_days']} из {kpi['expected_days']} дней периода,
    выручка за {kpi['revenue_days']} дней. Цель оценивается за полный месяц после сверки всех актов.
    {escape(kpi['notice'])}</p>
    <h3>Предварительный бюджет по группам</h3><p>{escape(budget.get('method', 'Недостаточно данных для распределения.'))}
    В выручке кондитерки учтены торты, песочка и мелкоштучка; распродажи отнесены к своей группе.
    Напитки и упаковка участвуют в общей выручке, но не получают долю бюджета пяти групп.</p>
    <div class="table-wrap"><table><thead><tr><th>Группа</th><th>Выручка группы, ₽</th><th>Ориентир потерь, ₽</th>
    <th>% выручки группы</th><th>Известные потери, ₽</th><th>Дней актов</th></tr></thead><tbody>{rows}</tbody></table></div>
    <p>Отсутствие актов остальных групп не означает нулевые потери. Остаточный бюджет кулинарии после фактических
    потерь остальных групп можно вычислить только с их полными актами.</p></section>'''


def render_matrix(proposal: dict) -> str:
    if not proposal:
        return ''
    labels = {'core': 'Постоянное ядро', 'rotation': 'Ротация', 'experiment': 'Тест'}
    rows = []
    for row in proposal['rows']:
        profit = row.get('profit_after_known_costs')
        margin = row.get('margin_after_known_costs')
        rows.append(f"<tr><td>{escape(str(row.get('sku', '')))}</td><td>{escape(row['name'])}</td>"
                    f"<td>{labels[row['role']]}</td><td>{row['sold'] if row.get('sold') is not None else 'нет истории'}</td>"
                    f"<td>{f'{profit:.2f}' if profit is not None else 'нужна себестоимость'}</td>"
                    f"<td>{f'{margin:.2f}' if margin is not None else '—'}</td></tr>")
    reserve = ''.join(f"<tr><td>{escape(row['name'])}</td><td>{row['sold']:g}</td>"
                      f"<td>{row['waste_quantity']:g}</td><td>{row['profit_after_known_costs']:.2f}</td></tr>"
                      for row in proposal.get('deprioritized', []))
    applied = 'Эти 32 блюда используются в текущем расчете заказа. Полный каталог доступных блюд сохранен.' if proposal.get('applied_to_order') else 'Предложение для выбора матрицы.'
    return f'''<section id="matrix"><h2>Матрица: {proposal['capacity']} поставляемых блюд</h2>
    <p>Кулинария ТТ стоит отдельно и не занимает эти места. Ядро {proposal['core_count']} / ротация {proposal['rotation_count']}
    / тест {proposal['experiment_count']}. Для полной матрицы 32 это 68,75% / 21,875% / 9,375% мест.
    Незанятых мест: {proposal['vacancies']}.</p><p>{applied}</p><p>Рейтинг: 50% вклад в прибыль после известных затрат,
    30% прибыль на проданную порцию, 20% количество продаж. Неполные акты ограничивают точность маржи.</p>
    <p>Прибыль здесь — валовая прибыль из продаж минус себестоимость найденных актов порчи и питания по конкретному блюду.
    Аренда, зарплата и прочие расходы не вычтены. Снятые блюда и снеки не включены. Строки с нулевой себестоимостью не получают преимущество.</p>
    <div class="table-wrap"><table><thead><tr><th>Артикул</th><th>Блюдо</th><th>Роль</th><th>Продано</th>
    <th>После известных затрат, ₽</th><th>Маржа, %</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
    <h3>Как проводить ротацию</h3><p>Ядро пересматривать раз в месяц. В 7 местах ротации менять по 2 блюда в неделю,
    сохраняя размер матрицы. Три тестовых места — для новых блюд; старт по 3 порции, тест 10–14 дней наличия,
    с отдельным учетом продаж, порчи и питания. Прежде чем заказать тестовое блюдо, проверить доступность и себестоимость.</p>
    <p>Сравнивать прибыль после затрат на день наличия и на место витрины, скорость продаж и потери, а не только процент маржи.
    Новинка заменяет слабое блюдо при большей прибыли и приемлемых списаниях; иначе возвращается в резерв.
    До учета времени отсутствия блюда продажи отражают нижнюю оценку спроса. Доли мест — стартовая политика, а не доказанный оптимум.</p>
    <p>На уровне глаз выделять блюда с высоким вкладом в прибыль и высокой прибылью на порцию; хиты по количеству держать доступными.
    Новинки размещать в трех выделенных местах и предлагать как альтернативу внутри того же приема пищи.
    Двухдневные пятничные блюда продаются в пятницу–субботу; на воскресенье их план равен нулю.</p>
    <details><summary>Резерв и блюда с ухудшившейся экономикой</summary><table><thead><tr><th>Блюдо</th><th>Продано</th>
    <th>Списано порций</th><th>После известных затрат, ₽</th></tr></thead><tbody>{reserve}</tbody></table></details></section>'''


def render_traffic(history: dict, forecast: list[dict]) -> str:
    if not history:
        return ''
    monthly = ''.join(f"<tr><td>{history['year']}-{row['month']:02d}</td><td>{row['paired_days']}</td>"
                      f"<td>{row['last_year_checks']}</td><td>{row['current_checks']}</td>"
                      f"<td>{row['change_percent'] if row['change_percent'] is not None else '—'}%</td></tr>"
                      for row in history['months'])
    daily = ''.join(f"<tr><td>{row['date']}</td><td>{row['checks']}</td><td>{row['revenue']:.2f}</td></tr>"
                    for row in history['previous_daily'])
    upcoming = ''.join(f"<tr><td>{row['date']}</td><td>{row['last_year_date']}</td>"
                       f"<td>{row['last_year_checks'] if row['last_year_checks'] is not None else '—'}</td>"
                       f"<td>{row['recent_expected_checks'] if row['recent_expected_checks'] is not None else '—'}</td>"
                       f"<td>{row['yoy_scale'] if row['yoy_scale'] is not None else '—'}</td>"
                       f"<td>{row['expected_checks'] if row['expected_checks'] is not None else '—'}</td>"
                       f"<td>{'учтена' if row['seasonality_applied'] else 'нет пар данных'}</td></tr>"
                       for row in forecast)
    return f'''<section id="traffic"><h2>Чеки: история {history['previous_year']} года и прогноз потока</h2>
    <p>История не суммируется повторно при перекрывающихся файлах. Таблица месяцев сравнивает только одинаковые календарные даты,
    имеющиеся в обоих годах. Для прогноза используется одинаковый день недели: дата минус 364 дня.</p>
    <p>Берем последние 4 одинаковых дня недели, оцениваем изменение к их парам прошлого года (минимум 3 пары).
    Прогноз = 50% недавний поток + 50% поток будущего аналогичного дня прошлого года × текущее изменение.
    При нехватке годовых пар остается недавний поток. Поправка к истории продаж блюда ограничена ×0,7…1,3,
    применяется один раз, только к гостевому спросу. Фактор по каждой позиции виден в заказе.</p>
    <div class="table-wrap"><table><thead><tr><th>Месяц</th><th>Парных дней</th><th>Чеки год назад</th><th>Чеки сейчас</th>
    <th>Изменение</th></tr></thead><tbody>{monthly}</tbody></table></div>
    <h3>Что учтено для следующих дней</h3><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Аналог прошлого года</th>
    <th>Чеков год назад</th><th>Недавний поток</th><th>Изменение год к году, ×</th><th>Прогноз чеков</th><th>Сезонность</th>
    </tr></thead><tbody>{upcoming}</tbody></table></div>
    <details><summary>Посмотреть все загруженные дни {history['previous_year']} года</summary><div class="table-wrap"><table>
    <thead><tr><th>Дата</th><th>Чеков</th><th>Выручка всей пекарни, ₽</th></tr></thead><tbody>{daily}</tbody></table></div></details></section>'''
