import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "fact_layer.db")

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    cursor = conn.cursor()
    
    # Documents table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        file_hash TEXT NOT NULL,
        upload_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        page_count INTEGER NOT NULL,
        chunk_count INTEGER NOT NULL
    );
    """)
    
    # Chunks table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id TEXT NOT NULL,
        page_number INTEGER NOT NULL,
        chunk_index INTEGER NOT NULL,
        text TEXT NOT NULL,
        start_char INTEGER NOT NULL,
        end_char INTEGER NOT NULL,
        token_count INTEGER NOT NULL,
        FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
    );
    """)

    # Facts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id TEXT NOT NULL,
        chunk_id INTEGER NOT NULL,
        subject TEXT NOT NULL DEFAULT 'Unknown Entity',
        entity TEXT NOT NULL DEFAULT 'Unknown Entity',
        metric TEXT NOT NULL DEFAULT 'General Assertion',
        predicate TEXT NOT NULL DEFAULT 'states',
        value TEXT NOT NULL,
        numeric_value REAL,
        unit TEXT,
        normalized_value REAL,
        normalized_unit TEXT,
        period TEXT,
        as_of_date TEXT,
        scope TEXT,
        qualifiers TEXT,
        raw_quote TEXT NOT NULL,
        page INTEGER NOT NULL,
        extraction_confidence REAL NOT NULL DEFAULT 1.0,
        grounding_confidence REAL NOT NULL DEFAULT 1.0,
        final_confidence REAL NOT NULL DEFAULT 1.0,
        extraction_method TEXT NOT NULL DEFAULT 'llm',
        validation_status TEXT NOT NULL DEFAULT 'valid',
        validation_notes TEXT,
        FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
        FOREIGN KEY (chunk_id) REFERENCES chunks (id) ON DELETE CASCADE
    );
    """)

    # Ensure missing columns in facts table are added if DB existed previously
    cursor.execute("PRAGMA table_info(facts);")
    existing_cols = {row[1] for row in cursor.fetchall()}
    
    needed_cols = [
        ("subject", "TEXT NOT NULL DEFAULT 'Unknown Entity'"),
        ("entity", "TEXT NOT NULL DEFAULT 'Unknown Entity'"),
        ("metric", "TEXT NOT NULL DEFAULT 'General Assertion'"),
        ("numeric_value", "REAL"),
        ("normalized_value", "REAL"),
        ("normalized_unit", "TEXT"),
        ("period", "TEXT"),
        ("as_of_date", "TEXT"),
        ("scope", "TEXT"),
        ("qualifiers", "TEXT"),
        ("extraction_method", "TEXT NOT NULL DEFAULT 'llm'"),
        ("validation_status", "TEXT NOT NULL DEFAULT 'valid'"),
        ("validation_notes", "TEXT")
    ]
    for col_name, col_def in needed_cols:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE facts ADD COLUMN {col_name} {col_def};")

    # Rejected Extractions table (Task 8)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rejected_extractions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id TEXT NOT NULL,
        page INTEGER NOT NULL,
        candidate_text TEXT NOT NULL,
        attempted_extraction TEXT,
        failure_type TEXT NOT NULL,
        rejection_reason TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
    );
    """)

    # Fact Relationships table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fact_relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fact_id_a INTEGER NOT NULL,
        fact_id_b INTEGER NOT NULL,
        relationship_type TEXT NOT NULL,
        reasoning TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 1.0,
        confidence_delta REAL NOT NULL DEFAULT 0.0,
        comparison_delta REAL NOT NULL DEFAULT 0.0,
        reconciliation_type TEXT NOT NULL DEFAULT 'NONE',
        FOREIGN KEY (fact_id_a) REFERENCES facts (id) ON DELETE CASCADE,
        FOREIGN KEY (fact_id_b) REFERENCES facts (id) ON DELETE CASCADE
    );
    """)

    # Ensure missing columns in fact_relationships
    cursor.execute("PRAGMA table_info(fact_relationships);")
    rel_cols = {row[1] for row in cursor.fetchall()}
    if "confidence" not in rel_cols:
        cursor.execute("ALTER TABLE fact_relationships ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0;")
    if "confidence_delta" not in rel_cols:
        cursor.execute("ALTER TABLE fact_relationships ADD COLUMN confidence_delta REAL NOT NULL DEFAULT 0.0;")
    if "comparison_delta" not in rel_cols:
        cursor.execute("ALTER TABLE fact_relationships ADD COLUMN comparison_delta REAL NOT NULL DEFAULT 0.0;")
    if "reconciliation_type" not in rel_cols:
        cursor.execute("ALTER TABLE fact_relationships ADD COLUMN reconciliation_type TEXT NOT NULL DEFAULT 'NONE';")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized cleanly with extended schema.")
