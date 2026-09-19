PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS snapshot (
    snapshot_id TEXT PRIMARY KEY,
    manifest_sha256 TEXT NOT NULL,
    source_system TEXT NOT NULL,
    acquired_at TEXT,
    application_version TEXT,
    source_schema_version TEXT,
    import_scope TEXT,
    source_person_count INTEGER NOT NULL,
    source_family_count INTEGER NOT NULL,
    source_child_link_count INTEGER NOT NULL,
    source_event_count INTEGER NOT NULL,
    source_place_count INTEGER NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TRIGGER IF EXISTS prevent_snapshot_identity_update;

CREATE TRIGGER IF NOT EXISTS guard_snapshot_conflicting_insert
BEFORE INSERT ON snapshot
WHEN EXISTS (
    SELECT 1
    FROM snapshot
    WHERE snapshot_id = NEW.snapshot_id
      AND manifest_sha256 != NEW.manifest_sha256
)
BEGIN
    SELECT RAISE(ABORT, 'snapshot manifest conflict');
END;

CREATE TRIGGER IF NOT EXISTS prevent_snapshot_reinsert
BEFORE INSERT ON snapshot
WHEN EXISTS (
    SELECT 1
    FROM snapshot
    WHERE snapshot_id = NEW.snapshot_id
      AND manifest_sha256 = NEW.manifest_sha256
)
BEGIN
    SELECT RAISE(ABORT, 'snapshot records are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_snapshot_update
BEFORE UPDATE ON snapshot
BEGIN
    SELECT RAISE(ABORT, 'snapshot records are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_snapshot_delete
BEFORE DELETE ON snapshot
BEGIN
    SELECT RAISE(ABORT, 'snapshot records are append-only');
END;

CREATE TABLE IF NOT EXISTS research_batch_input (
    research_batch_input_id INTEGER PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    resolved_path TEXT NOT NULL,
    acquisition_root TEXT NOT NULL,
    registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_id, resolved_path)
);

CREATE INDEX IF NOT EXISTS idx_research_batch_input_resolved_path
    ON research_batch_input(resolved_path);

CREATE TABLE IF NOT EXISTS person (
    person_id TEXT PRIMARY KEY,
    living INTEGER NOT NULL CHECK (living IN (0, 1)),
    private INTEGER NOT NULL CHECK (private IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS person_identifier (
    person_identifier_id INTEGER PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person(person_id),
    system TEXT NOT NULL,
    value TEXT NOT NULL,
    scope_snapshot_id TEXT REFERENCES snapshot(snapshot_id),
    first_seen_snapshot_id TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    last_seen_snapshot_id TEXT NOT NULL REFERENCES snapshot(snapshot_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_person_identifier_global
    ON person_identifier(system, value)
    WHERE scope_snapshot_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_person_identifier_scoped
    ON person_identifier(system, scope_snapshot_id, value)
    WHERE scope_snapshot_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_person_identifier_external
    ON person_identifier(system, value);
CREATE INDEX IF NOT EXISTS idx_person_identifier_person
    ON person_identifier(person_id);

CREATE TABLE IF NOT EXISTS person_identifier_observation (
    person_identifier_observation_id INTEGER PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    observation_ordinal INTEGER NOT NULL,
    person_identifier_id INTEGER NOT NULL
        REFERENCES person_identifier(person_identifier_id),
    person_id TEXT NOT NULL REFERENCES person(person_id),
    external_person_id TEXT NOT NULL,
    system TEXT NOT NULL,
    value TEXT NOT NULL,
    source_link_id TEXT NOT NULL,
    UNIQUE(snapshot_id, observation_ordinal)
);

CREATE INDEX IF NOT EXISTS idx_person_identifier_observation_external
    ON person_identifier_observation(
        snapshot_id, system, source_link_id, external_person_id
    );
CREATE INDEX IF NOT EXISTS idx_person_identifier_observation_stable
    ON person_identifier_observation(person_identifier_id);
CREATE INDEX IF NOT EXISTS idx_person_identifier_observation_person
    ON person_identifier_observation(person_id);

CREATE TRIGGER IF NOT EXISTS prevent_identifier_observation_reinsert
BEFORE INSERT ON person_identifier_observation
WHEN EXISTS (
    SELECT 1
    FROM person_identifier_observation
    WHERE snapshot_id = NEW.snapshot_id
      AND observation_ordinal = NEW.observation_ordinal
)
BEGIN
    SELECT RAISE(ABORT, 'raw observations are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_identifier_observation_update
BEFORE UPDATE ON person_identifier_observation
BEGIN
    SELECT RAISE(ABORT, 'raw observations are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_identifier_observation_delete
BEFORE DELETE ON person_identifier_observation
BEGIN
    SELECT RAISE(ABORT, 'raw observations are append-only');
END;

CREATE TABLE IF NOT EXISTS source (
    source_id INTEGER PRIMARY KEY,
    snapshot_id TEXT REFERENCES snapshot(snapshot_id),
    source_type TEXT NOT NULL,
    repository TEXT,
    collection_name TEXT,
    record_title TEXT NOT NULL,
    jurisdiction TEXT,
    volume TEXT,
    page TEXT,
    url TEXT,
    accessed_at TEXT,
    evidence_tier TEXT NOT NULL CHECK (
        evidence_tier IN (
            'original_record',
            'derivative_record',
            'authored_narrative',
            'family_knowledge',
            'tree_aggregate'
        )
    ),
    citation_text TEXT,
    UNIQUE(snapshot_id, source_type, record_title)
);

CREATE TABLE IF NOT EXISTS research_source_key (
    snapshot_id TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    source_key TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES source(source_id),
    PRIMARY KEY(snapshot_id, source_key),
    UNIQUE(snapshot_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_research_source_key_source
    ON research_source_key(source_id);

CREATE TABLE IF NOT EXISTS source_file (
    source_file_id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE CHECK (
        length(sha256) = 64
        AND sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    local_path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    rights_label TEXT NOT NULL CHECK (
        rights_label IN (
            'public_domain',
            'personal_research',
            'restricted',
            'private_family'
        )
    ),
    ocr_status TEXT NOT NULL CHECK (
        ocr_status IN ('not_started', 'raw', 'corrected', 'not_applicable')
    ),
    transcription_status TEXT NOT NULL CHECK (
        transcription_status IN (
            'not_started',
            'partial',
            'complete',
            'not_applicable'
        )
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_source_file_local_path
    ON source_file(local_path);

CREATE TABLE IF NOT EXISTS source_file_location (
    source_file_location_id INTEGER PRIMARY KEY,
    source_file_id INTEGER NOT NULL REFERENCES source_file(source_file_id),
    resolved_path TEXT NOT NULL,
    acquisition_root TEXT NOT NULL,
    registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_file_id, resolved_path)
);

CREATE INDEX IF NOT EXISTS idx_source_file_location_resolved_path
    ON source_file_location(resolved_path);

CREATE TABLE IF NOT EXISTS source_file_link (
    source_file_link_id INTEGER PRIMARY KEY,
    source_file_id INTEGER NOT NULL REFERENCES source_file(source_file_id),
    source_id INTEGER NOT NULL REFERENCES source(source_id),
    UNIQUE(source_file_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_source_file_link_source
    ON source_file_link(source_id);

CREATE TABLE IF NOT EXISTS place (
    place_id INTEGER PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    raw_external_place_id TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    place_type INTEGER,
    normalized_identity TEXT,
    latitude REAL,
    longitude REAL,
    coordinate_precision TEXT,
    historical_jurisdiction TEXT,
    normalization_method TEXT,
    normalization_confidence TEXT CHECK (
        normalization_confidence IS NULL OR normalization_confidence IN (
            'accepted_working',
            'plausible_lead',
            'quarantined_contradiction'
        )
    ),
    UNIQUE(snapshot_id, raw_external_place_id)
);

CREATE INDEX IF NOT EXISTS idx_place_raw_text ON place(raw_text);
CREATE INDEX IF NOT EXISTS idx_place_normalized_identity
    ON place(normalized_identity);

CREATE TABLE IF NOT EXISTS assertion (
    assertion_id INTEGER PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    subject_person_id TEXT REFERENCES person(person_id),
    predicate TEXT NOT NULL,
    value_text TEXT,
    raw_value TEXT,
    parsed_value TEXT,
    snapshot_id TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    source_id INTEGER NOT NULL REFERENCES source(source_id),
    place_id INTEGER REFERENCES place(place_id),
    raw_external_assertion_id TEXT NOT NULL,
    raw_external_owner_id TEXT NOT NULL,
    raw_external_place_id TEXT,
    is_private INTEGER NOT NULL DEFAULT 0 CHECK (is_private IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(
        snapshot_id,
        predicate,
        raw_external_assertion_id,
        subject_type,
        subject_id
    )
);

CREATE INDEX IF NOT EXISTS idx_assertion_subject
    ON assertion(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_assertion_subject_person
    ON assertion(subject_person_id);
CREATE INDEX IF NOT EXISTS idx_assertion_predicate ON assertion(predicate);
CREATE INDEX IF NOT EXISTS idx_assertion_source ON assertion(source_id);
CREATE INDEX IF NOT EXISTS idx_assertion_snapshot ON assertion(snapshot_id);

CREATE TABLE IF NOT EXISTS person_observation (
    person_observation_id INTEGER PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    observation_ordinal INTEGER NOT NULL,
    person_id TEXT NOT NULL REFERENCES person(person_id),
    external_person_id TEXT NOT NULL,
    primary_name_id TEXT NOT NULL,
    primary_name TEXT NOT NULL,
    surname TEXT NOT NULL,
    given_name TEXT NOT NULL,
    suffix TEXT NOT NULL,
    sex INTEGER NOT NULL,
    living INTEGER NOT NULL CHECK (living IN (0, 1)),
    private INTEGER NOT NULL CHECK (private IN (0, 1)),
    source_parent_family_id TEXT,
    primary_name_assertion_id INTEGER NOT NULL
        REFERENCES assertion(assertion_id),
    selected_parent_assertion_id INTEGER
        REFERENCES assertion(assertion_id),
    UNIQUE(snapshot_id, observation_ordinal)
);

CREATE INDEX IF NOT EXISTS idx_person_observation_external
    ON person_observation(snapshot_id, external_person_id);
CREATE INDEX IF NOT EXISTS idx_person_observation_person
    ON person_observation(person_id);
CREATE INDEX IF NOT EXISTS idx_person_observation_sex
    ON person_observation(sex);

CREATE TRIGGER IF NOT EXISTS prevent_person_observation_reinsert
BEFORE INSERT ON person_observation
WHEN EXISTS (
    SELECT 1
    FROM person_observation
    WHERE snapshot_id = NEW.snapshot_id
      AND observation_ordinal = NEW.observation_ordinal
)
BEGIN
    SELECT RAISE(ABORT, 'raw observations are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_person_observation_update
BEFORE UPDATE ON person_observation
BEGIN
    SELECT RAISE(ABORT, 'raw observations are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_person_observation_delete
BEFORE DELETE ON person_observation
BEGIN
    SELECT RAISE(ABORT, 'raw observations are append-only');
END;

CREATE TABLE IF NOT EXISTS event_observation (
    event_observation_id INTEGER PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    observation_ordinal INTEGER NOT NULL,
    assertion_id INTEGER NOT NULL REFERENCES assertion(assertion_id),
    person_id TEXT REFERENCES person(person_id),
    place_id INTEGER REFERENCES place(place_id),
    external_event_id TEXT NOT NULL,
    owner_type INTEGER NOT NULL,
    external_owner_id TEXT NOT NULL,
    external_family_id TEXT,
    fact_type_id TEXT NOT NULL,
    fact_type_name TEXT NOT NULL,
    raw_date TEXT NOT NULL,
    date_modifier TEXT NOT NULL,
    date_start_year INTEGER,
    date_start_month INTEGER,
    date_start_day INTEGER,
    date_end_year INTEGER,
    date_end_month INTEGER,
    date_end_day INTEGER,
    date_parse_status TEXT NOT NULL,
    external_place_id TEXT,
    raw_place_name TEXT,
    details TEXT NOT NULL,
    note TEXT NOT NULL,
    private INTEGER NOT NULL CHECK (private IN (0, 1)),
    UNIQUE(snapshot_id, observation_ordinal)
);

CREATE INDEX IF NOT EXISTS idx_event_observation_external
    ON event_observation(snapshot_id, external_event_id);
CREATE INDEX IF NOT EXISTS idx_event_observation_person
    ON event_observation(person_id);
CREATE INDEX IF NOT EXISTS idx_event_observation_fact_type
    ON event_observation(fact_type_id, fact_type_name);

CREATE TRIGGER IF NOT EXISTS prevent_event_observation_reinsert
BEFORE INSERT ON event_observation
WHEN EXISTS (
    SELECT 1
    FROM event_observation
    WHERE snapshot_id = NEW.snapshot_id
      AND observation_ordinal = NEW.observation_ordinal
)
BEGIN
    SELECT RAISE(ABORT, 'raw observations are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_event_observation_update
BEFORE UPDATE ON event_observation
BEGIN
    SELECT RAISE(ABORT, 'raw observations are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_event_observation_delete
BEFORE DELETE ON event_observation
BEGIN
    SELECT RAISE(ABORT, 'raw observations are append-only');
END;

CREATE TABLE IF NOT EXISTS relationship_assertion (
    relationship_assertion_id INTEGER PRIMARY KEY,
    subject_person_id TEXT NOT NULL REFERENCES person(person_id),
    predicate TEXT NOT NULL,
    object_person_id TEXT NOT NULL REFERENCES person(person_id),
    role TEXT,
    snapshot_id TEXT NOT NULL REFERENCES snapshot(snapshot_id),
    source_id INTEGER NOT NULL REFERENCES source(source_id),
    raw_external_relationship_id TEXT NOT NULL,
    raw_external_family_id TEXT NOT NULL,
    raw_external_child_link_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_relationship_provenance
    ON relationship_assertion(
        snapshot_id,
        predicate,
        subject_person_id,
        object_person_id,
        COALESCE(role, ''),
        raw_external_relationship_id
    );
CREATE INDEX IF NOT EXISTS idx_relationship_subject
    ON relationship_assertion(subject_person_id);
CREATE INDEX IF NOT EXISTS idx_relationship_object
    ON relationship_assertion(object_person_id);
CREATE INDEX IF NOT EXISTS idx_relationship_predicate
    ON relationship_assertion(predicate);
CREATE INDEX IF NOT EXISTS idx_relationship_source
    ON relationship_assertion(source_id);

CREATE TABLE IF NOT EXISTS conclusion (
    conclusion_id INTEGER PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    chosen_assertion_id INTEGER REFERENCES assertion(assertion_id),
    chosen_relationship_assertion_id INTEGER
        REFERENCES relationship_assertion(relationship_assertion_id),
    confidence TEXT NOT NULL CHECK (
        confidence IN (
            'accepted_working',
            'plausible_lead',
            'quarantined_contradiction'
        )
    ),
    rationale TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (chosen_assertion_id IS NOT NULL) !=
        (chosen_relationship_assertion_id IS NOT NULL)
    ),
    UNIQUE(subject_type, subject_id, predicate)
);

CREATE INDEX IF NOT EXISTS idx_conclusion_subject
    ON conclusion(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_conclusion_confidence
    ON conclusion(confidence);

CREATE TABLE IF NOT EXISTS cohort_membership (
    cohort_membership_id INTEGER PRIMARY KEY,
    person_id TEXT NOT NULL REFERENCES person(person_id),
    cohort_code TEXT NOT NULL CHECK (cohort_code IN ('A', 'B', 'C', 'D', 'Z')),
    inclusion_reason TEXT NOT NULL,
    derivation_method TEXT NOT NULL CHECK (
        derivation_method IN ('computed', 'curated', 'background')
    ),
    source_id INTEGER REFERENCES source(source_id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(person_id, cohort_code)
);

CREATE INDEX IF NOT EXISTS idx_cohort_code
    ON cohort_membership(cohort_code);

CREATE TABLE IF NOT EXISTS research_question (
    research_question_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('open', 'in_progress', 'resolved', 'paused')
    ),
    target_people_json TEXT NOT NULL DEFAULT '[]',
    target_relationships_json TEXT NOT NULL DEFAULT '[]',
    planned_searches TEXT,
    negative_results TEXT,
    current_conclusion TEXT,
    working_confidence TEXT CHECK (
        working_confidence IS NULL OR working_confidence IN (
            'accepted_working',
            'plausible_lead',
            'quarantined_contradiction'
        )
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_research_question_status
    ON research_question(status);

CREATE UNIQUE INDEX IF NOT EXISTS ux_research_question_title
    ON research_question(title);
