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
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        value TEXT NOT NULL,
        unit TEXT,
        time_scope TEXT,
        raw_quote TEXT NOT NULL,
        page INTEGER NOT NULL,
        extraction_confidence REAL NOT NULL DEFAULT 1.0,
        grounding_confidence REAL NOT NULL DEFAULT 1.0,
        final_confidence REAL NOT NULL DEFAULT 1.0,
        FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
        FOREIGN KEY (chunk_id) REFERENCES chunks (id) ON DELETE CASCADE
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
        confidence_delta REAL NOT NULL DEFAULT 0.0,
        FOREIGN KEY (fact_id_a) REFERENCES facts (id) ON DELETE CASCADE,
        FOREIGN KEY (fact_id_b) REFERENCES facts (id) ON DELETE CASCADE
    );
    """)
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized cleanly.")
