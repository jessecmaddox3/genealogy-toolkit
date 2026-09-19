"""Invented regressions for impossible relationships and reversed intervals."""
from dataclasses import replace
import json

import pytest

from genealogy.research_records import load_research_batch
from genealogy.research_store import ingest_research_batch
from genealogy.rm_dates import parse_rm_date
from genealogy.rm_reader import extract_snapshot
from genealogy.store import create_store,ingest_snapshot
from tests.fixtures.research_batch import valid_research_payload
from tests.fixtures.rm_fixture import build_rm_fixture


@pytest.mark.parametrize('raw',[
    'DR+18880423..+18880422..',
    'DR+18890000..+18880000..',
    'DR+18880500..+18880400..',
])
def test_reversed_interval_preserves_raw_without_claiming_it_is_parsed(raw):
    result=parse_rm_date(raw)
    assert result.original==raw
    assert result.parse_status=='unparsed'


@pytest.mark.parametrize('raw',[
    'DR+18880423..+18880423..',
    'DR+18880000..+18880400..',
    'DR+18880423..+18880000..',
])
def test_overlapping_partial_intervals_do_not_gain_false_precision(raw):
    result=parse_rm_date(raw)
    assert result.parse_status=='parsed'
    if raw.endswith('+18880000..'):assert result.end.month is None and result.end.day is None


def test_research_same_key_self_parent_is_rejected_before_ingestion(tmp_path):
    payload=valid_research_payload();edge=payload['relationships'][0];edge['parent_key']=edge['child_key']
    path=tmp_path/'input.json';path.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='own parent'):load_research_batch(path)


def test_different_keys_resolving_to_same_person_roll_back_every_write(tmp_path):
    payload=valid_research_payload()
    payload['people'][1]['familysearch_id']=payload['people'][0]['familysearch_id']
    for source in payload['sources']:source['file']=None
    path=tmp_path/'input.json';path.write_text(json.dumps(payload))
    batch=load_research_batch(path);connection=create_store(tmp_path/'store.sqlite')
    with pytest.raises(ValueError,match='own parent'):ingest_research_batch(connection,batch,tmp_path,batch_path=path)
    for table in ['snapshot','person','source','assertion','relationship_assertion','conclusion']:
        assert connection.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,table


def test_raw_snapshot_self_parent_without_dates_is_retained_but_quarantined(tmp_path):
    path=build_rm_fixture(tmp_path/'invented.rmtree');snapshot=extract_snapshot(path,'synthetic-self-parent')
    edge=next(x for x in snapshot.relationships if x.kind=='parent_child')
    snapshot=replace(snapshot,events=(),relationships=(replace(edge,subject_person_id=edge.object_person_id),))
    connection=create_store(tmp_path/'store.sqlite');ingest_snapshot(connection,snapshot,'f'*64)
    rows=connection.execute('''SELECT relationship.subject_person_id,relationship.object_person_id,current.confidence,current.rationale
      FROM relationship_assertion AS relationship JOIN conclusion AS current
      ON current.chosen_relationship_assertion_id=relationship.relationship_assertion_id''').fetchall()
    assert len(rows)==1 and rows[0][0]==rows[0][1]
    assert rows[0][2]=='quarantined_contradiction'
    assert 'self_parent' in rows[0][3]

from genealogy.records import RawPerson, RawRelationship, RawSnapshot
from genealogy.seeds import PrivateSeed, SeedPerson, SeedRelationship, ingest_private_seed


def _curated(tmp_path, edges, batch_id='invented-integrity'):
    payload=valid_research_payload();payload['batch_id']=batch_id
    template=payload['people'][0]
    payload['people']=[dict(template,key=key,display_name='Invented '+key,familysearch_id=None) for key in ['example-child','example-parent','extra']]
    edge_template=payload['relationships'][0]
    payload['relationships']=[dict(edge_template,key='edge-'+str(i),parent_key=parent,child_key=child,role=role,confidence='accepted_working') for i,(parent,child,role) in enumerate(edges)]
    for source in payload['sources']:source['file']=None
    path=tmp_path/(batch_id+'.json');path.write_text(json.dumps(payload))
    return load_research_batch(path)


@pytest.mark.parametrize('edges,signal',[
    ([('example-parent','example-child','father'),('example-child','example-parent','mother')],'ancestry_cycle'),
    ([('example-parent','example-child','father'),('example-parent','example-child','mother')],'conflicting_parent_roles'),
    ([('example-parent','example-child','father'),('extra','example-child','father')],'competing_parent_choices'),
])
def test_curated_invalid_working_graph_rolls_back(tmp_path,edges,signal):
    connection=create_store(tmp_path/'store.sqlite')
    with pytest.raises(ValueError,match=signal):ingest_research_batch(connection,_curated(tmp_path,edges),tmp_path)
    for table in ['snapshot','person','assertion','relationship_assertion','conclusion']:
        assert connection.execute('SELECT count(*) FROM '+table).fetchone()[0]==0


def test_curated_cycle_checks_existing_accepted_edges(tmp_path):
    connection=create_store(tmp_path/'store.sqlite')
    ingest_research_batch(connection,_curated(tmp_path,[('example-parent','example-child','father')],'first'),tmp_path)
    before=connection.execute('SELECT count(*) FROM snapshot').fetchone()[0]
    with pytest.raises(ValueError,match='ancestry_cycle'):
        ingest_research_batch(connection,_curated(tmp_path,[('example-child','example-parent','mother')],'second'),tmp_path)
    assert connection.execute('SELECT count(*) FROM snapshot').fetchone()[0]==before


def test_unspecified_parent_roles_preserve_both_current_conclusions(tmp_path):
    connection=create_store(tmp_path/'store.sqlite')
    ingest_research_batch(connection,_curated(tmp_path,[('example-parent','example-child',None),('extra','example-child',None)]),tmp_path)
    assert connection.execute("SELECT count(*) FROM conclusion WHERE predicate='parent_child' AND confidence='accepted_working'").fetchone()[0]==2


@pytest.mark.parametrize('edges',[ [('alpha','alpha')], [('alpha','beta'),('beta','alpha')] ])
def test_programmatic_seed_rejects_self_and_longer_cycles_atomically(tmp_path,edges):
    seed=PrivateSeed(tuple(SeedPerson(key,'Invented '+key,False) for key in ['alpha','beta']),tuple(SeedRelationship(a,b) for a,b in edges))
    connection=create_store(tmp_path/'store.sqlite')
    with pytest.raises(ValueError):ingest_private_seed(connection,seed)
    assert connection.execute('SELECT count(*) FROM person').fetchone()[0]==0


def _raw_graph(edges):
    snapshot='synthetic-integrity'
    people=tuple(RawPerson(snapshot,key,key,'Invented '+key,'Invented',key,'',0,False,False,None) for key in ['alpha','beta','gamma'])
    relationships=tuple(RawRelationship(snapshot,'parent_child',a,b,role,'family-'+str(i),'edge-'+str(i)) for i,(a,b,role) in enumerate(edges))
    return RawSnapshot(snapshot,people,(),relationships,(),(),len(edges),len(edges))


@pytest.mark.parametrize('edges,signal',[
    ([('alpha','beta','father'),('beta','alpha','mother')],'ancestry_cycle'),
    ([('alpha','beta','father'),('alpha','beta','mother')],'conflicting_parent_roles'),
    ([('alpha','gamma','father'),('beta','gamma','father')],'competing_parent_choices'),
])
def test_raw_conflicts_retain_all_claims_but_quarantine_working_edges(tmp_path,edges,signal):
    connection=create_store(tmp_path/'store.sqlite');ingest_snapshot(connection,_raw_graph(edges),'synthetic-digest')
    assert connection.execute('SELECT count(*) FROM relationship_assertion').fetchone()[0]==2
    rows=connection.execute("SELECT confidence,rationale FROM conclusion WHERE predicate='parent_child'").fetchall()
    assert len(rows)==2 and all(c=='quarantined_contradiction' and signal in r for c,r in rows)


@pytest.mark.parametrize('reverse_order',[False, True])
def test_curated_conflicting_evidence_retained_without_row_order_choice(tmp_path,reverse_order):
    connection=create_store(tmp_path/'store.sqlite')
    batch=_curated(tmp_path,[('example-parent','example-child','father'),('extra','example-child','father')])
    relationships=(batch.relationships[0],replace(batch.relationships[1],confidence='quarantined_contradiction'))
    if reverse_order:relationships=relationships[::-1]
    ingest_research_batch(connection,replace(batch,relationships=relationships),tmp_path)
    assert sorted(connection.execute("SELECT confidence FROM conclusion WHERE predicate='parent_child'").fetchall())==[('accepted_working',),('quarantined_contradiction',)]


@pytest.mark.parametrize('reverse_order',[False, True])
def test_same_edge_differently_rated_claims_both_survive(tmp_path,reverse_order):
    connection=create_store(tmp_path/'store.sqlite')
    batch=_curated(tmp_path,[('example-parent','example-child','father')])
    relationships=(batch.relationships[0],replace(batch.relationships[0],key='contrary-claim',confidence='plausible_lead'))
    if reverse_order:relationships=relationships[::-1]
    ingest_research_batch(connection,replace(batch,relationships=relationships),tmp_path)
    assert sorted(connection.execute("SELECT confidence FROM conclusion WHERE predicate='parent_child'").fetchall())==[('accepted_working',),('plausible_lead',)]


def test_later_raw_snapshot_cannot_resolve_previous_conflict_by_repeating_one_claim(tmp_path):
    from genealogy.records import RawIdentifier
    connection=create_store(tmp_path/'store.sqlite')
    first=_raw_graph([('alpha','gamma','father'),('beta','gamma','father')])
    first=replace(first,identifiers=tuple(RawIdentifier(first.snapshot_id,p.external_person_id,'familysearch','TEST-'+str(i+101),str(i)) for i,p in enumerate(first.people)))
    ingest_snapshot(connection,first,'first-hash')
    snapshot_id='synthetic-second'
    second=replace(first,snapshot_id=snapshot_id,people=tuple(replace(p,snapshot_id=snapshot_id) for p in first.people),identifiers=tuple(replace(p,snapshot_id=snapshot_id) for p in first.identifiers),relationships=(replace(first.relationships[0],snapshot_id=snapshot_id),))
    ingest_snapshot(connection,second,'second-hash')
    row=connection.execute("SELECT c.confidence,c.rationale FROM conclusion c JOIN relationship_assertion r ON r.relationship_assertion_id=c.chosen_relationship_assertion_id WHERE r.snapshot_id=?",(snapshot_id,)).fetchone()
    assert row[0]=='quarantined_contradiction' and 'prior_unresolved_relationship_conflict' in row[1]


@pytest.mark.parametrize('reverse_order',[False, True])
def test_raw_same_snapshot_reviews_do_not_depend_on_row_order(tmp_path,reverse_order):
    snapshot=_raw_graph([('alpha','gamma','father'),('alpha','gamma','father')])
    contradicted=snapshot.relationships[0]
    annotations={('relationship','parent_child','alpha','gamma','father','child_link:'+contradicted.source_child_link_id):{'contradictions':['synthetic_source_conflict']}}
    if reverse_order:snapshot=replace(snapshot,relationships=snapshot.relationships[::-1])
    connection=create_store(tmp_path/'store.sqlite');ingest_snapshot(connection,snapshot,'invented-hash',confidence_annotations=annotations)
    rows=connection.execute("SELECT r.raw_external_child_link_id,c.confidence FROM relationship_assertion r JOIN conclusion c ON c.chosen_relationship_assertion_id=r.relationship_assertion_id ORDER BY r.raw_external_child_link_id").fetchall()
    assert rows==[('edge-0','quarantined_contradiction'),('edge-1','accepted_working')]


def test_curated_resolution_corroboration_and_new_conflict_keep_history(tmp_path):
    from genealogy.records import RawIdentifier
    from genealogy.identity import add_global_identifier
    connection=create_store(tmp_path/'store.sqlite')
    first=_raw_graph([('alpha','gamma','father'),('beta','gamma','father')])
    first=replace(first,identifiers=tuple(RawIdentifier(first.snapshot_id,p.external_person_id,'familysearch','TEST-'+str(i+201),str(i)) for i,p in enumerate(first.people)))
    ingest_snapshot(connection,first,'first-hash')
    ids=dict(connection.execute("SELECT value,person_id FROM person_identifier WHERE system='rootsmagic_rin'"))
    for key,raw in [('example-parent','alpha'),('extra','beta'),('example-child','gamma')]:
        add_global_identifier(connection,person_id=ids[raw],system='research_key',value='research:'+key,snapshot_id=first.snapshot_id)
    ingest_research_batch(connection,_curated(tmp_path,[('example-parent','example-child','father')],'resolution'),tmp_path)
    for sid,relationship in [('corroboration',first.relationships[0]),('renewed-conflict',first.relationships[1])]:
        snapshot=replace(first,snapshot_id=sid,people=tuple(replace(p,snapshot_id=sid) for p in first.people),identifiers=tuple(replace(p,snapshot_id=sid) for p in first.identifiers),relationships=(replace(relationship,snapshot_id=sid),))
        ingest_snapshot(connection,snapshot,sid+'-hash')
        rows=connection.execute("SELECT confidence FROM conclusion WHERE predicate='parent_child'").fetchall()
        assert rows and all(row[0]==('accepted_working' if sid=='corroboration' else 'quarantined_contradiction') for row in rows)
    assert connection.execute('SELECT count(*) FROM relationship_assertion').fetchone()[0]==5
