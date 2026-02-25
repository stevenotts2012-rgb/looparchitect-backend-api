import sqlite3

conn = sqlite3.connect('test.db')
cursor = conn.cursor()

# Check if arrangements table exists
cursor.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='arrangements'"
)
result = cursor.fetchone()

if result:
    print('✓ Arrangements table exists')
    cursor.execute('PRAGMA table_info(arrangements)')
    columns = cursor.fetchall()
    print(f'  Total columns: {len(columns)}')
    print('  First 5 columns:')
    for col in columns[:5]:
        print(f'    - {col[1]} ({col[2]})')
else:
    print('✗ Arrangements table not found')
    # List all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f'  Available tables: {[t[0] for t in tables]}')

conn.close()
