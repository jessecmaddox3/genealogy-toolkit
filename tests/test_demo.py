"""Public demo and HTML export behaviors, using invented data only."""
import json
from pathlib import Path
import socket
import sqlite3

import pytest

from genealogy.cli import main
from genealogy.demo import make_demo, TITLE
from genealogy.report_page import render_research_page


def test_complete_demo_offline_and_sources_unchanged(tmp_path, monkeypatch):
    def no_network(*args,**kwargs):raise AssertionError('Demo attempted network access')
    monkeypatch.setattr(socket,'socket',no_network)
    output=tmp_path/'demo';page=make_demo(output)
    assert page.is_file()
    verification=json.loads((output/'demo-verification.json').read_text())
    assert verification['rootsmagic_people']==8 and verification['canonical_people']==10
    assert verification['changed_manifest_rejected'] and verification['raw_snapshot_replay_no_changes'] and verification['research_replay_no_changes']
    assert verification['familysearch_ids']==0
    from genealogy.snapshots import sha256_file
    assert json.loads((output/'manifest.json').read_text())['files'][0]['sha256']==sha256_file(output/'synthetic-rootsmagic.rmtree')
    with sqlite3.connect(output/'demo.sqlite') as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()==('ok',)
        assert conn.execute("SELECT count(*) FROM person_identifier WHERE system='familysearch'").fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM person WHERE living=1 AND private=1').fetchone()[0]==2
        assert conn.execute("SELECT count(*) FROM event_observation WHERE date_parse_status='unparsed'").fetchone()[0]==1
        assert conn.execute("SELECT count(*) FROM conclusion WHERE confidence='quarantined_contradiction'").fetchone()[0]>=1
    assert len(list((output/'research').iterdir()))==6
    assert 'Which Ari Fable' in (output/'research'/'index.html').read_text()
    before=(output/'manifest.json').read_bytes()
    with pytest.raises(ValueError,match='never replaced'):make_demo(output)
    assert (output/'manifest.json').read_bytes()==before


def test_research_html_escapes_untrusted_text():
    rendered=render_research_page({'title':'<script>alert(1)</script>'},{'person-dossier.md':'# <img src=x onerror=alert(1)>\n| <script> | safe |\n|---|---|\n| entry | value |','research-state.json':'{"bad":"</pre><script>"}'})
    assert '<script>' not in rendered and '<img src=x' not in rendered
    assert '&lt;script&gt;' in rendered and 'Content-Security-Policy' in rendered


def test_cli_html_report_preserves_five_outputs_and_adds_reader(tmp_path):
    output=tmp_path/'demo';assert main(['demo','--output',str(output)])==0
    reports=tmp_path/'reports';reports.mkdir()
    assert main(['research-report','--database',str(output/'demo.sqlite'),'--question-title',TITLE,'--output-dir',str(reports),'--html'])==0
    assert {p.name for p in reports.iterdir()}=={'index.html','direct-line-audit.md','person-dossier.md','hypothesis-matrix.md','action-queue.md','research-state.json'}


@pytest.mark.parametrize('which',['markdown','json'])
@pytest.mark.parametrize('protected',['mock-sources/workshop.txt','research-example.json'])
@pytest.mark.parametrize('alias',['direct','hardlink'])
def test_coverage_never_replaces_registered_evidence_or_input(tmp_path,which,protected,alias):
    output=tmp_path/'demo';make_demo(output)
    source=output/protected;before=source.read_bytes();target=source
    if alias=='hardlink':
        target=tmp_path/'alias';target.hardlink_to(source)
    clean=tmp_path/'clean-output';clean.write_text('existing report remains')
    paths={'markdown':clean,'json':clean};paths[which]=target
    assert main(['coverage','--database',str(output/'demo.sqlite'),'--cohort','A','--markdown',str(paths['markdown']),'--json',str(paths['json'])])==2
    assert source.read_bytes()==before and clean.read_text()=='existing report remains'


def test_html_report_cannot_replace_a_registered_source(tmp_path):
    output=tmp_path/'demo';make_demo(output)
    source=output/'mock-sources/workshop.txt';before=source.read_bytes()
    reports=tmp_path/'report';reports.mkdir();(reports/'index.html').hardlink_to(source)
    assert main(['research-report','--database',str(output/'demo.sqlite'),'--question-title',TITLE,'--output-dir',str(reports),'--html'])==2
    assert source.read_bytes()==before and len(list(reports.iterdir()))==1


def test_init_store_refuses_to_modify_an_unrelated_sqlite_database(tmp_path):
    source=tmp_path/'unrelated.sqlite'
    with sqlite3.connect(source) as connection:
        connection.execute('CREATE TABLE preserved_note(text TEXT)');connection.execute("INSERT INTO preserved_note VALUES ('invented source')")
    before=source.read_bytes()
    assert main(['init-store','--database',str(source)])==2
    assert source.read_bytes()==before


def test_manifest_cannot_replace_an_unrelated_existing_file(tmp_path):
    source=tmp_path/'invented.txt';source.write_text('invented acquisition')
    output=tmp_path/'important.txt';output.write_text('preserve this invented source')
    assert main(['manifest','--root',str(tmp_path),'--output',str(output),str(source)])==2
    assert output.read_text()=='preserve this invented source'


def test_manifest_can_update_its_own_output(tmp_path):
    source=tmp_path/'invented.txt';source.write_text('first invented acquisition')
    output=tmp_path/'manifest.json';args=['manifest','--root',str(tmp_path),'--output',str(output),str(source)]
    assert main(args)==0
    before=output.read_bytes();source.write_text('second invented acquisition')
    assert main(args)==0 and output.read_bytes()!=before
