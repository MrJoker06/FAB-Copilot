"""Exercise actual static responses without importing app.main or opening databases."""
import asyncio
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from html.parser import HTMLParser
from pathlib import Path

import httpx

from app.api.application import create_application
from app.api.routers.system import create_router as system_router


class PageView(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.active_views = []
        self.current_navigation = []
        self.initial_view = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'body':
            self.initial_view = attrs.get('data-initial-view')
        if tag == 'section' and {'view', 'active'}.issubset(attrs.get('class', '').split()):
            self.active_views.append(attrs['id'])
        if 'data-view' in attrs and attrs.get('aria-current') == 'page':
            self.current_navigation.append(attrs['data-view'])


class PassThrough:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)


@asynccontextmanager
async def no_lifespan(app):
    yield


class DisplayMaterialsTests(unittest.TestCase):
    def page_app(self):
        root = Path(__file__).resolve().parents[1]
        app = self.make_app(root)
        runtime = {'APP_VERSION':'offline-test', '_VERSIONED_PAGE_TEMPLATES':{
            name:root / 'app/static' / f'{name}.html' for name in ('index','admin')}}
        app.include_router(system_router(lambda:runtime).router)
        return app

    def test_initial_http_html_selects_requested_view_before_javascript(self):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.page_app()),base_url='http://local') as client:
                for name in ('dashboard','reports','procedures','autosystem','capability','knowledge','sessions','cases'):
                    response = await client.get('/',params={'view':name})
                    self.assertEqual(response.status_code,200)
                    page = PageView(response.text)
                    expected = 'procedures' if name == 'cases' else name
                    self.assertEqual(page.active_views,[expected+'View'])
                    self.assertEqual(page.initial_view,expected)
                    self.assertEqual(page.current_navigation,[] if expected == 'sessions' else [expected])
                    self.assertNotIn('__ACTIVE_',response.text)
                    self.assertNotIn('__INITIAL_VIEW__',response.text)
                    self.assertNotIn('__CURRENT_',response.text)
        asyncio.run(run())

    def test_default_and_unknown_views_fall_back_without_reflecting_input(self):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.page_app()),base_url='http://local') as client:
                for parameters in ({},{'view':''},{'view':'unknown'},{'view':'reports\" onload=alert(1)'},{'view':'<script>alert(1)</script>'}):
                    response = await client.get('/',params=parameters)
                    self.assertEqual(response.status_code,200)
                    page = PageView(response.text)
                    self.assertEqual(page.active_views,['dashboardView'])
                    self.assertEqual(page.current_navigation,['dashboard'])
                    self.assertNotIn('alert(1)',response.text)
                admin = await client.get('/admin',params={'view':'reports'})
                self.assertIn('id="adminWorkspace"',admin.text)
                self.assertNotIn('data-initial-view=',admin.text)
        asyncio.run(run())

    def make_app(self, root):
        return create_application(
            lifespan=no_lifespan,
            project_dir=root,
            principal_context_middleware=PassThrough,
            request_audit_middleware=PassThrough,
        )

    def test_real_materials_and_all_report_links_are_readable(self):
        root = Path(__file__).resolve().parents[1]

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.make_app(root)), base_url='http://local') as client:
                response = await client.get('/display_mock_data/catalog.json')
                self.assertEqual(response.status_code, 200)
                catalog = response.json()
                self.assertTrue(catalog['synthetic'])
                self.assertEqual(len(catalog['reports']), 6)
                self.assertEqual(len(catalog['documents']), 6)
                ids = {item['id'] for item in catalog['documents']}
                for item in catalog['documents']:
                    if item.get('related_sop'):
                        self.assertIn(item['related_sop'], ids)
                for item in catalog['reports']:
                    report = await client.get(item['url'])
                    self.assertEqual(report.status_code, 200)
                    self.assertIn(item['title'], report.text)
                    self.assertIn('<table>', report.text)
                    self.assertIn('no-cache', report.headers['cache-control'])
                    self.assertNotIn('演示', report.text)

        asyncio.run(run())

    def test_optional_directory_missing_and_path_escape_are_404(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root/'app/static').mkdir(parents=True)
            outside = root/'private.json'
            outside.write_text(json.dumps({'private': 'not public'}), encoding='utf-8')

            async def run():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.make_app(root)), base_url='http://local') as client:
                    self.assertEqual((await client.get('/display_mock_data/catalog.json')).status_code, 404)
                (root/'display_mock_data').mkdir()
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.make_app(root)), base_url='http://local') as client:
                    for path in ['/display_mock_data/%2e%2e/private.json', '/display_mock_data/missing.json']:
                        response = await client.get(path)
                        self.assertEqual(response.status_code, 404)
                        self.assertNotIn('not public', response.text)

            asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
