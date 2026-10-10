"""Offline provider, worker, and CLI checks with simulated browser responses."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from termin import cli, storage
from termin.model import Model
from termin.providers import berlin, doctolib
from termin.ui import setup
from termin.workers import berlin as berlin_worker
from termin.workers import doctolib as doctolib_worker


def watch(name='Example'):
    return {'sid': 1, 'name': name, 'district': '', 'book': 'https://example.test/booking'}


@contextlib.contextmanager
def fake_playwright():
    browser = MagicMock()
    page = MagicMock()
    page.is_closed.return_value = False
    browser.pages = [page]
    chromium = MagicMock()
    chromium.launch.return_value = browser
    chromium.launch_persistent_context.return_value = browser
    manager = MagicMock()
    manager.__enter__.return_value = SimpleNamespace(chromium=chromium)
    api = SimpleNamespace(sync_playwright=lambda: manager, Error=RuntimeError)
    with patch.dict(sys.modules, {'playwright': SimpleNamespace(), 'playwright.sync_api': api}):
        yield browser


class ProviderTests(unittest.TestCase):
    def test_berlin_calendar_combines_and_sorts_two_pages(self):
        page = MagicMock()
        page.title.return_value = 'Calendar'
        page.query_selector.return_value = None
        day = '<a aria-label="{} - An diesem Tag einen Termin buchen">'
        page.content.side_effect = [
            day.format('02.11.2099') + '<a aria-label="zu nächstem Monat" href="/terminvereinbarung/termin/day/123/">',
            day.format('20.10.2099') + day.format('02.11.2099'),
        ]
        browser = MagicMock()
        context = browser.new_context.return_value
        context.new_page.return_value = page
        self.assertEqual(berlin.check_location(browser, 'https://example.test'),
                         (['20.10.2099', '02.11.2099'], 'ok'))
        self.assertEqual(page.goto.call_count, 2)
        context.close.assert_called_once()

    def test_berlin_access_failures_keep_their_status_and_close_context(self):
        for title, html, expected in [('Unerwünschter Zugriff', '', 'blocked'),
                                       ('Calendar', 'Zu viele Zugriffe', 'throttled')]:
            with self.subTest(expected=expected):
                browser = MagicMock()
                context = browser.new_context.return_value
                page = context.new_page.return_value
                page.title.return_value = title
                page.content.return_value = html
                page.query_selector.return_value = None
                self.assertEqual(berlin.check_location(browser, 'https://example.test'), ([], expected))
                context.close.assert_called_once()

    def test_doctolib_response_capture_and_listener_cleanup(self):
        page = MagicMock()
        page.url = 'https://example.test/booking'
        page.query_selector.return_value = None
        response = SimpleNamespace(status=200, url='https://example.test/availabilities.json',
                                   text=lambda: json.dumps({'availabilities': []}))
        listeners = {}
        page.on.side_effect = lambda event, callback: listeners.update({event: callback})
        def navigate(*args, **kwargs):
            listeners['response'](response)
            return SimpleNamespace(status=200)
        page.goto.side_effect = navigate
        feed, bodies, reason = doctolib.dl_load(page, page.url)
        self.assertEqual(feed, response.url)
        self.assertEqual(bodies, [response.text()])
        self.assertIsNone(reason)
        page.remove_listener.assert_called_once_with('response', listeners['response'])

    def test_doctolib_check_merges_multiple_feed_windows(self):
        bodies = [json.dumps({'availabilities': [{'slots': [slot]}]})
                  for slot in ['2099-10-20T10:00', '2099-10-20T09:00', '2099-10-20T10:00']]
        with patch.object(doctolib, 'dl_load', return_value=('feed', bodies, None)), patch.object(doctolib, 'log_debug'):
            result = doctolib.dl_check(None, watch())
        self.assertEqual(result, (['2099-10-20T09:00', '2099-10-20T10:00'], None, 'feed', None))


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(interval=240, once=True, open=False, sound='unused')

    def test_berlin_once_alerts_and_skips_paused_offices(self):
        paused = dict(watch('Paused'), paused=True)
        model = Model(121151, 'Passport', [watch(), paused], 240)
        with fake_playwright() as browser, \
                patch.object(berlin_worker, 'check_location', return_value=(['20.10.2099'], 'ok')) as check, \
                patch.object(berlin_worker, 'notify') as notify, \
                patch.object(berlin_worker, 'play_sound') as sound, \
                patch.object(berlin_worker, 'log_debug'):
            berlin_worker.monitor_worker(model, self.args, lambda: None)
        self.assertEqual(model.cycle, 1)
        self.assertEqual(model.state['Example']['status'], 'available')
        self.assertEqual(model.state['Paused']['status'], 'paused')
        self.assertFalse(model.checking)
        check.assert_called_once()
        notify.assert_called_once()
        sound.assert_called_once_with('unused', times=3)
        browser.close.assert_called_once()

    def test_doctolib_once_seeds_baseline_then_alerts_for_new_day(self):
        item = watch()
        model = Model(None, 'Doctors', [item], 240, 'doctolib')
        saved_ledger = {}
        with fake_playwright(), \
                patch.object(doctolib_worker, 'load_ledger', return_value=saved_ledger), \
                patch.object(doctolib_worker, 'save_ledger') as save, \
                patch.object(doctolib_worker, 'save_doctolib'), \
                patch.object(doctolib_worker, 'dl_check', side_effect=[
                    (['2099-10-20T09:00'], None, 'feed', None),
                    (['2099-10-20T09:00', '2099-10-21T09:00'], None, 'feed', None)]), \
                patch.object(doctolib_worker, 'notify') as notify, \
                patch.object(doctolib_worker, 'play_sound') as sound, \
                patch.object(doctolib_worker, 'log_debug'):
            doctolib_worker.doctolib_worker(model, self.args, lambda: None)
            self.assertTrue(item['seeded'])
            self.assertEqual(model.state['Example']['status'], 'available')
            notify.assert_not_called()
            model.next_at = 0
            doctolib_worker.doctolib_worker(model, self.args, lambda: None)
            notify.assert_called_once_with('Doctolib: Example', 'New bookable day: 21.10.2099')
            sound.assert_called_once_with('unused', times=3)
            self.assertEqual(save.call_count, 2)
        self.assertEqual(model.cycle, 2)
        self.assertFalse(model.checking)


class CliTests(unittest.TestCase):
    def test_explicit_berlin_flags_resolve_and_persist_selection(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(storage, 'CONFIG_FILE', Path(directory) / 'config.json'), \
                patch.object(cli, 'log_debug'), \
                patch.object(setup, 'discover', return_value=('Passport', [watch()])), \
                patch.object(cli, 'run_headless') as run, \
                patch.object(sys, 'argv', ['termin_monitor.py', '-s', 'passport', '-o', 'all', '--once']):
            cli.main()
            args, model = run.call_args.args
            self.assertTrue(args.once)
            self.assertEqual(model.mode, 'berlin')
            self.assertEqual(model.service_id, 121151)
            self.assertEqual(storage.load_config()['offices'][0]['book'], watch()['book'])

    def test_saved_doctolib_mode_selects_doctolib_worker(self):
        with patch.object(cli, 'load_config', return_value={'mode': 'doctolib', 'doctolib': [watch()]}), \
                patch.object(cli, 'log_debug'), patch.object(cli, 'run_headless') as run, \
                patch.object(sys, 'argv', ['termin_monitor.py', '--once']):
            cli.main()
        args, model, worker = run.call_args.args
        self.assertTrue(args.once)
        self.assertEqual(model.mode, 'doctolib')
        self.assertIs(worker, doctolib_worker.doctolib_worker)

    def test_list_services_does_not_load_configuration(self):
        with patch.object(cli, 'load_config') as load, \
                patch.object(sys, 'argv', ['termin_monitor.py', '--list-services']), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            cli.main()
        load.assert_not_called()
        self.assertIn('citizenship-test', output.getvalue())
        self.assertIn('passport', output.getvalue())


if __name__ == '__main__':
    unittest.main()
