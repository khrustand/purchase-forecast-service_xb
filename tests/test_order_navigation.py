from datetime import date, datetime
from html.parser import HTMLParser
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from src.app import web_server as web
from src.app.order_navigation import upcoming_order_dates


class DateTabParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.in_dates = False
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'nav' and values.get('class') == 'order-date-tabs':
            self.in_dates = True
        if tag == 'a' and self.in_dates:
            self.links.append(values)

    def handle_endtag(self, tag):
        if tag == 'nav':
            self.in_dates = False


class OrderNavigationTests(TestCase):
    def test_six_deliveries_and_existing_cutoff_across_months(self):
        self.assertEqual(upcoming_order_dates(datetime(2026, 11, 18, 17, 59)),
                         ['2026-11-20', '2026-11-23', '2026-11-25', '2026-11-27', '2026-11-30', '2026-12-02'])
        self.assertEqual(upcoming_order_dates(datetime(2026, 11, 18, 18)),
                         ['2026-11-23', '2026-11-25', '2026-11-27', '2026-11-30', '2026-12-02', '2026-12-04'])

    def test_tabs_stay_in_place_and_open_existing_selected_order(self):
        from tests.synthetic_sales import dashboard_fixture
        clock = datetime(2026, 11, 18, 12)
        dates = upcoming_order_dates(clock)
        with dashboard_fixture(web):
            for value in dates:
                with self.subTest(date=value):
                    payload = web.build_dashboard_payload(start_day=date.fromisoformat(value), now=clock,
                                                          service_level=.9, profit_tolerance=0)
                    strategy = payload['culinary_strategy']
                    self.assertEqual(strategy['future_orders'][0]['start'], value)
                    self.assertEqual(len(strategy['future_orders']), 4)  # Existing calculation scope is unchanged.
                    html = web.render_dashboard_html(payload)
                    links = DateTabParser(html).links
                    queries = [parse_qs(urlsplit(link['href']).query) for link in links]
                    self.assertEqual([query['start'][0] for query in queries], dates)
                    self.assertEqual([query['days'] for query in queries], [['14']] * 6)
                    self.assertEqual([query['service'] for query in queries], [['90']] * 6)
                    self.assertEqual([query['reserve_cost'] for query in queries], [['0']] * 6)
                    active = [query['start'][0] for link, query in zip(links, queries) if link.get('aria-current') == 'page']
                    self.assertEqual(active, [value])
                    self.assertLess(html.index('</header>'), html.index('<nav class="order-date-tabs"'))
                    self.assertLess(html.index('<nav class="order-date-tabs"'), html.index('Как учитывается погода'))
                    current = strategy['future_orders'][0]
                    self.assertEqual(sum(day['quantity'] for day in current['daily_totals']), current['total_quantity'])

    def test_no_extra_navigation_in_production_or_analytics(self):
        from tests.synthetic_sales import dashboard_fixture
        with dashboard_fixture(web):
            payload = web.build_dashboard_payload(now=datetime(2026, 11, 18, 12))
        for view in ('production', 'analytics'):
            self.assertNotIn('<nav class="order-date-tabs"', web.render_dashboard_html(payload, view=view))

    def test_selected_tab_uses_the_existing_query_parameters(self):
        with patch.object(web, 'build_dashboard_payload') as build:
            web._payload_from_query('start=2026-12-02&days=14&service=90&reserve_cost=0')
        self.assertEqual(build.call_args.kwargs, {'start_day': date(2026, 12, 2), 'horizon_days': 14,
                                                 'service_level': .9, 'profit_tolerance': 0})
