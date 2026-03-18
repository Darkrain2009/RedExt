# db_setup.py

import sqlite3

def setup_database():
    conn = sqlite3.connect('c2_server.db')
    cursor = conn.cursor()

    # Agents table (with optional columns for status, hostname, etc.)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS agents (
        agent_id TEXT PRIMARY KEY,
        hostname TEXT,
        status TEXT DEFAULT 'offline',
        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        notes TEXT DEFAULT ''
    )
    ''')

    # Add notes column to existing databases that don't have it yet
    try:
        cursor.execute("ALTER TABLE agents ADD COLUMN notes TEXT DEFAULT ''")
    except Exception:
        pass  # Column already exists

    # Tasks table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        task_id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT NOT NULL,
        description TEXT,
        command TEXT NOT NULL,
        parameters TEXT,
        status TEXT DEFAULT 'pending',
        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
    )
    ''')

    # Data records for exfiltrated data
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS data_records (
        data_id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id TEXT NOT NULL,
        data_type TEXT,
        payload TEXT,
        task_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (agent_id) REFERENCES agents(agent_id),
        FOREIGN KEY (task_id) REFERENCES tasks(task_id)
    )
    ''')

    # Add task_id column to existing databases that don't have it yet
    try:
        cursor.execute('ALTER TABLE data_records ADD COLUMN task_id INTEGER REFERENCES tasks(task_id)')
    except Exception:
        pass  # Column already exists

    # Activity / audit log
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        agent_id TEXT,
        details TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.commit()
    conn.close()
    print("Database setup complete.")

if __name__ == "__main__":
    setup_database()
