"""A standalone, escaped HTML reader for the same five research outputs."""
from html import escape
import re

STYLE = '''
:root{color-scheme:light;--ink:#173c3a;--paper:#faf6ec;--accent:#ad4a2e;--line:#d7d1c3}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.65 system-ui,sans-serif}
main{max-width:1120px;margin:auto;padding:48px 24px}header{max-width:850px}h1{font:clamp(2.1rem,6vw,4rem)/1.12 Georgia,serif;margin:14px 0 22px}h2{font:2rem/1.2 Georgia,serif}h3{font:1.3rem/1.3 Georgia,serif}
a{color:var(--accent);text-underline-offset:3px}a:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:4px}.eyebrow{font-size:.76rem;letter-spacing:.12em;text-transform:uppercase;font-weight:750}
.lead{font-size:1.18rem}.note,.card{padding:22px;border:1px solid var(--line);border-radius:12px;background:#fffdf7}.note{border-left:5px solid var(--accent)}
nav{display:flex;flex-wrap:wrap;gap:12px;margin:30px 0}nav a{padding:12px 16px;border:1px solid var(--line);border-radius:8px;background:#fffdf7}
section{margin:36px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:18px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.6 ui-monospace,monospace;max-width:100%}code{overflow-wrap:anywhere}details{border-top:1px solid var(--line);padding:20px 0}summary{cursor:pointer;font-weight:700;min-height:44px}
.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{border:1px solid var(--line);padding:9px;vertical-align:top;text-align:left}p,li{overflow-wrap:anywhere}img{max-width:100%;height:auto;border-radius:12px}.muted{font-size:.9rem;color:#526761}footer{border-top:1px solid var(--line);padding-top:22px;margin-top:40px}
@media(max-width:500px){main{padding:28px 18px}.note,.card{padding:16px}}
@media print{body{background:white;font-size:10pt}main{padding:0;max-width:none}nav,.no-print{display:none}h1{font-size:26pt}h2{font-size:18pt}details{break-inside:avoid}a{color:inherit}.table-scroll{overflow:visible}}
'''


def markdown_fragment(text: str) -> str:
    """Render our controlled report format; all input is escaped, no raw HTML."""
    result=[];table=[];items=[]
    def inline(value):
        value=escape(value)
        value=re.sub(r"`([^`]+)`",r"<code>\1</code>",value)
        return re.sub(r"\*\*([^*]+)\*\*",r"<strong>\1</strong>",value)
    def flush_items():
        if items:
            result.append('<ul>'+''.join('<li>'+inline(item)+'</li>' for item in items)+'</ul>');items.clear()
    def flush():
        if table:
            rows=[]
            for i,row in enumerate(table):
                if set(row.replace('|','').replace(':','').replace('-','').strip())==set():continue
                tag='th' if i==0 else 'td'
                rows.append('<tr>'+''.join(f'<{tag}>'+inline(cell.strip())+f'</{tag}>' for cell in row.strip('|').split('|'))+'</tr>')
            result.append('<div class="table-scroll"><table>'+''.join(rows)+'</table></div>');table.clear()
    for line in text.splitlines():
        if line.startswith('|'):flush_items();table.append(line);continue
        flush()
        if line.startswith('- '):items.append(line[2:]);continue
        flush_items()
        if line.startswith('#'):
            level=min(len(line)-len(line.lstrip('#'))+1,4)
            result.append(f'<h{level}>'+inline(line.lstrip('# ').strip())+f'</h{level}>')
        elif line.strip():result.append('<p>'+inline(line)+'</p>')
    flush();flush_items();return '\n'.join(result)


def page(title: str, body: str) -> str:
    return '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src \'self\' data:; base-uri \'none\'; form-action \'none\'"><title>'+escape(title)+'</title><style>'+STYLE+'</style></head><body><main>'+body+'</main></body></html>\n'


def render_research_page(state: dict, outputs: dict[str,str]) -> str:
    title=str(state.get('title','Research question'))
    labels={'direct-line-audit.md':'Line audit','person-dossier.md':'Person dossier','hypothesis-matrix.md':'Hypotheses','action-queue.md':'Next actions','research-state.json':'Full research state'}
    navigation=''.join('<a href="#report-'+str(i)+'">'+labels[name]+'</a>' for i,name in enumerate(outputs))
    body='<header><p class="eyebrow">Evidence-first Genealogy / Research reader</p><h1>'+escape(title)+'</h1><p class="lead">Keep the source, the claim, and your current conclusion together.</p></header><aside class="note"><strong>Working research, with its uncertainty intact.</strong> These outputs contain the information you supplied. Review them before sharing. Evidence labels are human judgments, not proof scores.</aside><nav aria-label="Reports">'+navigation+'</nav>'
    for i,(name,text) in enumerate(outputs.items()):
        rendered='<details><summary>Show the complete portable research state</summary><pre>'+escape(text)+'</pre></details>' if name.endswith('.json') else markdown_fragment(text)
        body+='<section id="report-'+str(i)+'"><h2>'+labels[name]+'</h2><p><a href="'+escape(name,quote=True)+'" download>Download '+escape(name)+'</a></p>'+rendered+'</section>'
    return page(title,body+'<footer>Generated locally with Evidence-first Genealogy. No scripts, trackers, external fonts, or automatic requests.</footer>')
