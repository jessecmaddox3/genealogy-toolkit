"""Wholly invented offline demonstration, independently authored for this release."""
from dataclasses import asdict
from html import escape
import json
from pathlib import Path
import sqlite3

from genealogy.cohorts import recompute_cohorts
from genealogy.coverage import build_coverage_report
from genealogy.identity import add_global_identifier
from genealogy.render import render_coverage_json, render_coverage_markdown
from genealogy.report_page import page, render_research_page
from genealogy.research_records import load_research_batch
from genealogy.research_render import load_research_state, render_research_outputs
from genealogy.research_store import ingest_research_batch
from genealogy.rm_reader import extract_snapshot
from genealogy.seeds import load_private_seed, ingest_private_seed
from genealogy.snapshots import build_manifest, write_manifest, sha256_file
from genealogy.store import create_store, ingest_snapshot, SnapshotConflictError

TITLE='Which Ari Fable appears in the Larkhaven workshop register?'


def _json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8')


def synthetic_rootsmagic(path: Path) -> None:
    """Create a schema-compatible teaching fixture; no proprietary bytes."""
    with sqlite3.connect(path) as connection:
        connection.executescript(Path(__file__).with_name('demo_schema.sql').read_text())
        people=[(101,'Ari','Fable',1,1830),(102,'Mira','Fable',2,1802),(103,'Oren','Quill',0,1824),(104,'Neri','Fable',0,1774),(105,'Tavi','Glass',0,1776),(106,'Sola','Fable',2,1806),(107,'Dove','Rook',0,1810),(108,'Ari','Fable',0,1846)]
        for pid,given,surname,family,year in people:
            connection.execute('INSERT INTO PersonTable VALUES (?,?,?,?,?,?)',(pid,0,0,0,family,'Wholly invented teaching record'))
            connection.execute('INSERT INTO NameTable VALUES ('+','.join('?'*23)+')',(pid,pid,surname,given,'','','',0,'.',0,1,0,0,'','Synthetic example',year,0,'','',0,'','',''))
            date=f'D.+{year}0000..+00000000..'
            connection.execute('INSERT INTO EventTable VALUES ('+','.join('?'*16)+')',(pid,1,0,pid,0,1,date,0,1,0,0,0,'Invented','Year-only birth','',0))
        for fid,father,mother in [(1,103,102),(2,104,105),(3,106,107)]:
            connection.execute('INSERT INTO FamilyTable VALUES ('+','.join('?'*16)+')',(fid,father,mother,0,0,0,0,0,0,0,0,'','','','Invented family unit',0))
        for edge,child,family in [(1,101,1),(2,102,2),(3,106,2)]:
            connection.execute('INSERT INTO ChildTable VALUES ('+','.join('?'*11)+')',(edge,child,family,0,0,0,0,0,0,'Invented claim',0))
        connection.execute('INSERT INTO FactTypeTable VALUES ('+','.join('?'*11)+')',(1,0,'Birth','Birth','BIRT',0,1,1,'',0,0))
        connection.execute('INSERT INTO FactTypeTable VALUES ('+','.join('?'*11)+')',(2,0,'Workshop admission','Workshop','EVEN',1,1,1,'',0,0))
        connection.execute('INSERT INTO PlaceTable VALUES ('+','.join('?'*14)+')',(1,0,'Larkhaven, Mistvale, Fictional Republic','','','','',0,0,'Invented place',0,'','',0))
        # One supported partial interval and one explicitly unsupported raw value.
        for eid,pid,raw in [(201,101,'DR+18470400..+18470500..'),(202,108,'T.unspecified autumn fair')]:
            connection.execute('INSERT INTO EventTable VALUES ('+','.join('?'*16)+')',(eid,2,0,pid,0,1,raw,0,1,0,0,0,'','Invented workshop note','',0))
        # FamilySearchTable intentionally remains empty. No provider IDs or calls.


def research_payload() -> dict:
    """The narrative, people, topology, counts and sources are all invented."""
    def source(key,title,tier,filename=None,rights='public_domain'):
        return dict(key=key,source_type='teaching_mock',repository='Fictional Larkhaven Workshop Library',collection_name='Invented training collection',record_title=title,jurisdiction='Mistvale, Fictional Republic',volume='C',page='24',url=None,accessed_at='2037-04-09',evidence_tier=tier,citation_text=title+' (wholly invented teaching document), C:24.',file=None if filename is None else dict(path=filename,original_filename=Path(filename).name,rights_label=rights,ocr_status='not_applicable',transcription_status='complete'))
    sources=[source('register','MOCK: workshop register, spring 1847','original_record','mock-sources/workshop.txt'),source('index','MOCK: later alphabetical index','derivative_record','mock-sources/index.txt'),source('story','MOCK: community recollection','authored_narrative','data/private/mock-recollection.txt','restricted')]
    people=[dict(key=key,display_name=name,name_confidence='accepted_working',name_rationale='Invented teaching identity; no claim about a real person.',deceased=True,familysearch_id=None,source_key='register') for key,name in [('ari-1830','Ari Fable (born 1830)'),('ari-1846','Ari Fable (born 1846)'),('mira','Mira Fable'),('oren','Oren Quill')]]
    relationships=[dict(key='mira-parent',parent_key='mira',child_key='ari-1830',role='mother',source_key='register',confidence='accepted_working',rationale='The invented register explicitly names Mira as mother; this remains a working example.'),dict(key='oren-parent',parent_key='oren',child_key='ari-1830',role='father',source_key='index',confidence='quarantined_contradiction',rationale='The invented dates would make Oren six at the birth. Retain the copied claim for review; do not use it in the working lineage.')]
    assertions=[dict(key='birth-ari',person_key='ari-1830',source_key='register',predicate='event.birth',value_text='1830, year only',raw_value='1830',parsed_value={'modifier':'exact','start':{'year':1830,'month':None,'day':None},'end':None},confidence='accepted_working',rationale='Year is explicit in the invented entry; month and day remain unknown.'),dict(key='occupation-ari',person_key='ari-1830',source_key='story',predicate='event.occupation',value_text='Possibly a paper-maker',raw_value='a paper-maker, perhaps',parsed_value=None,confidence='plausible_lead',rationale='An invented later recollection supplies an uncertain lead, not established occupation.')]
    def search(key,target,status,action,result):
        return dict(key=key,repository='Fictional Larkhaven Workshop Library',collection='Invented workshop admissions',target=target,locator='C:24 and facing page',url=None,required_action=action,expected_value='Compare age, mother and workshop number to distinguish the two invented people.',destination_path='data/private/'+key+'.txt',status=status,result_summary=result)
    question=dict(title=TITLE,status='in_progress',summary='The older Ari fits the register age and named mother. The later index conflates two people; inspect the facing page before treating the identification as settled.',target_person_keys=['ari-1830','ari-1846'],line_anchor=[dict(person_key='ari-1830',basis='Invented workshop register',confidence='accepted_working',note='Identity is provisional; exact matching never merges people by name alone.')],timeline=[dict(date_text='1830',place_text='Larkhaven (invented)',event_text='Older Ari reportedly born; year only.',source_keys=['register']),dict(date_text='April to May 1847',place_text='Larkhaven (invented)',event_text='Workshop admits an apprentice named Ari Fable, aged seventeen.',source_keys=['register']),dict(date_text='1892',place_text=None,event_text='Later index assigns the entry to a same-named person born in 1846.',source_keys=['index'])],associates=[dict(name='Fen Dapple (invented)',relationship='workshop registrar',source_keys=['register'],note='Signature links the register pages, not a claimed relative.')],searches=[search('facing-page','Read the full facing page','planned','none',None),search('school-index','School index for workshop number','no_relevant_result','none','Invented index checked completely; no matching entry. This does not prove the person was absent.'),search('restricted-volume','Restricted duplicate volume','blocked','sign_in','Example access boundary only. No real account, archive, request or payment exists.')],hypotheses=[dict(key='older-ari',statement='The 1847 apprentice is Ari born in 1830.',rank=1,status='active',evidence=[dict(source_key='register',direction='supports',weight='high',rationale='Stated age and mother align in the invented text.'),dict(source_key='index',direction='conflicts',weight='low',rationale='The later index assigns the entry to the other Ari.')]),dict(key='younger-ari',statement='The 1847 apprentice is Ari born in 1846.',rank=2,status='rejected',evidence=[dict(source_key='register',direction='conflicts',weight='high',rationale='An infant cannot be the seventeen-year-old described in this fictional entry.')])])
    return dict(format_version=1,batch_id='larkhaven-workshop-demo-v1',people=people,sources=sources,assertions=assertions,relationships=relationships,question=question)


def make_demo(output: Path) -> Path:
    """Write only a new directory. Existing files, links and directories are refused."""
    output=Path(output)
    if output.exists() or output.is_symlink():raise ValueError('Choose a new demo output folder; existing paths are never replaced.')
    output.parent.mkdir(parents=True,exist_ok=True);output.mkdir()
    source=output/'synthetic-rootsmagic.rmtree';synthetic_rootsmagic(source)
    manifest=build_manifest([source],output);write_manifest(manifest,output/'manifest.json')
    snapshot=extract_snapshot(source,'synthetic-larkhaven-v1')
    connection=create_store(output/'demo.sqlite')
    try:
        digest=sha256_file(source);first=ingest_snapshot(connection,snapshot,digest);changes=connection.total_changes
        repeated=ingest_snapshot(connection,snapshot,digest)
        if repeated.people_added or connection.total_changes!=changes:raise RuntimeError('Demo replay was not idempotent')
        try:ingest_snapshot(connection,snapshot,'deliberately-different-demo-hash')
        except SnapshotConflictError:hash_rejected=True
        else:raise RuntimeError('Changed manifest hash should be rejected')
        # A deliberate, explicit crosswalk after reviewing this invented fixture.
        # This is not fuzzy name matching and never runs on user input.
        ids=dict(connection.execute("SELECT value,person_id FROM person_identifier WHERE system='rootsmagic_rin' AND scope_snapshot_id=?",(snapshot.snapshot_id,)))
        for key,rin in [('ari-1830','101'),('ari-1846','108'),('mira','102'),('oren','103')]:
            add_global_identifier(connection,person_id=ids[rin],system='research_key',value='research:'+key,snapshot_id=snapshot.snapshot_id)
        seed={'people':[{'seed_id':'invented-living-adult','display_name':'Demo Living Adult','living':True},{'seed_id':'invented-living-child','display_name':'Demo Living Child','living':True}],'relationships':[{'parent':'invented-living-adult','child':'invented-living-child'}]}
        _json(output/'private-seed-example.json',seed);ingest_private_seed(connection,load_private_seed(output/'private-seed-example.json'))
        mocks={'mock-sources/workshop.txt':'WHOLLY INVENTED TEACHING TEXT. Workshop register C:24, spring 1847. Ari Fable, age 17, mother Mira, workshop number 8. This is not an archival transcript.\n','mock-sources/index.txt':'WHOLLY INVENTED TEACHING TEXT. A later index confuses the 1847 apprentice with Ari Fable born 1846 and supplies Oren as father. This error is deliberate.\n','data/private/mock-recollection.txt':'WHOLLY INVENTED TEACHING TEXT. A later storyteller calls Ari a paper-maker, perhaps. Restricted is a demonstration label only; this file is authored for the demo.\n'}
        for name,text in mocks.items():
            path=output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
        _json(output/'research-example.json',research_payload());batch=load_research_batch(output/'research-example.json')
        ingest_research_batch(connection,batch,output,batch_path=output/'research-example.json')
        research_repeat=ingest_research_batch(connection,batch,output,batch_path=output/'research-example.json')
        if not research_repeat.repeated:raise RuntimeError('Research repeat was not idempotent')
        cohorts=recompute_cohorts(connection,ids['101']);_json(output/'cohorts.json',asdict(cohorts))
        report=build_coverage_report(connection,'A');(output/'coverage.md').write_text(render_coverage_markdown(report),encoding='utf-8');(output/'coverage.json').write_text(render_coverage_json(report),encoding='utf-8')
        state=load_research_state(connection,TITLE);outputs=render_research_outputs(state);reports=output/'research';reports.mkdir()
        for name,text in outputs.items():(reports/name).write_text(text,encoding='utf-8')
        (reports/'index.html').write_text(render_research_page(state,outputs),encoding='utf-8')
        verification={'all_content':'Wholly invented, including people, places, graph, chronology, aggregate counts and mock sources.','rootsmagic_people':first.people_added,'canonical_people':connection.execute('SELECT count(*) FROM person').fetchone()[0],'raw_snapshot_replay_no_changes':True,'changed_manifest_rejected':hash_rejected,'research_replay_no_changes':True,'familysearch_ids':0,'network_requests':0,'note':'Canonical UUIDs and local timestamps are newly generated per run; the fixture and semantic results are fixed.'}
        _json(output/'demo-verification.json',verification)
    finally:connection.close()
    body='<header><p class="eyebrow">Evidence-first Genealogy / Invented demo</p><h1>A name is a clue.<br>Evidence makes the case.</h1><p class="lead">Two people called Ari Fable. One workshop register. A copied relationship that does not add up.</p></header><aside class="note"><strong>Everything here is invented.</strong> People, dates, places, relationships and records were authored for this example. No family data, accounts or internet connection are needed.</aside><nav aria-label="Explore the example"><a href="research/index.html">Read the research</a><a href="coverage.md">Coverage report</a><a href="research-example.json" download>Editable research example</a><a href="demo-verification.json">Import checks</a></nav><section><h2>Follow a complete research loop</h2><div class="grid">'
    cards=[('1. Preserve what arrived','Read a synthetic RootsMagic snapshot without modifying it. Record file hashes and original observations.'),('2. Keep identities distinct','Same names do not trigger a merge. An explicit crosswalk links the selected invented records.'),('3. Question the link','An implausible parent-age claim stays in the evidence store, but leaves the accepted lineage.'),('4. Compare the sources','Read original-style mock text, a mistaken later index and a tentative recollection, with separate judgments.'),('5. Plan the next step','Keep the rejected hypothesis, negative search and blocked volume alongside the next useful question.'),('6. See what is missing','Recompute cohorts and coverage using explicit denominators rather than a misleading single completeness score.')]
    for title,description in cards:body+='<article class="card"><h3>'+escape(title)+'</h3><p>'+escape(description)+'</p></article>'
    body+='</div></section><section><h2>Your files stay yours</h2><p>The generated SQLite store and original five research outputs are in this folder. The HTML reader is a convenient view of those outputs. It does not upload, fetch, infer new ancestors or turn working judgments into verified facts.</p><p>Start with the research reader, then adapt <code>research-example.json</code> using the project guide. Use a separate private folder for your own records.</p></section><footer>Built for personal use and shared as a useful starting point. Make it your own, and improvements are welcome. Cheers!</footer>'
    (output/'index.html').write_text(page('Evidence-first Genealogy: invented example',body),encoding='utf-8')
    return output/'index.html'
