import sqlite3
conn = sqlite3.connect('parcelpilot.db')
cursor = conn.cursor()
cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
for row in cursor.fetchall():
    print(row[1])
