"""Offline, isolated browser check of the source demo and every readable output."""
from pathlib import Path
import sys
import tempfile
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from genealogy.demo import make_demo

with tempfile.TemporaryDirectory(prefix='genealogy-browser-') as directory:
    output=Path(directory)/'demo';make_demo(output)
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context()
        outside=[];errors=[]
        def route(request):
            outside.append(request.request.url);request.abort()
        context.route('http://**/*',route);context.route('https://**/*',route)
        page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        for width in [320,390,768,1440]:
            page.set_viewport_size({'width':width,'height':900})
            page.goto((output/'index.html').as_uri())
            assert page.title()=='Evidence-first Genealogy: invented example'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
            page.get_by_role('link',name='Read the research').click()
            assert page.get_by_role('heading',level=1).inner_text().startswith('Which Ari Fable')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
            assert page.locator('details').count()==1 and not page.locator('details').evaluate('(node)=>node.open')
            page.get_by_text('Show the complete portable research state',exact=True).click()
            assert page.locator('details').evaluate('(node)=>node.open')
            assert 'no_relevant_result' in page.locator('details').inner_text()
            links=page.locator('a[download]').evaluate_all('(nodes)=>nodes.map(n=>n.getAttribute("href"))')
            assert len(links)==5 and all((output/'research'/name).is_file() for name in links)
        assert not outside,outside
        assert not errors,errors
        context.close();browser.close()
print('Offline demo, four widths, HTML reader, five downloads and JSON disclosure passed; no outside requests.')
