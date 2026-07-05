import sqlite3, sys, os
p = r"c:\Desktop\study\Machine Learning Projects\portfolio\Ajay-Prakash-Pandey\site.db"
print('DB path:', p)
print('Exists:', os.path.exists(p), 'Is file:', os.path.isfile(p))
try:
    conn = sqlite3.connect(p)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1;")
    print('OK, sample table:', cur.fetchone())
    conn.close()
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
