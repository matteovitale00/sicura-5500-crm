from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
import hashlib
import csv
import io
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = 'sicura5500crm2024xk92'

# Use /data volume mount on Railway (persistent), fall back to local for dev
_data_dir = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', os.path.dirname(__file__))
os.makedirs(_data_dir, exist_ok=True)
DB_PATH = os.path.join(_data_dir, 'crm.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS prospects (
            id INTEGER PRIMARY KEY,
            sponsor_name TEXT NOT NULL,
            plan_name TEXT,
            ein TEXT,
            city TEXT,
            state TEXT,
            industry TEXT,
            plan_assets REAL,
            num_participants INTEGER,
            fees_pct_assets REAL,
            total_fees REAL,
            fee_tier TEXT,
            contact_name TEXT,
            phone TEXT,
            email TEXT,
            mailer_sent_date TEXT,
            stage TEXT DEFAULT "Mailer Sent",
            stage_entered_at TEXT,
            notes TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS call_logs (
            id INTEGER PRIMARY KEY,
            prospect_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            timestamp TEXT,
            note TEXT NOT NULL,
            FOREIGN KEY (prospect_id) REFERENCES prospects(id)
        );
    ''')
    for uname, pw, dname in [('matteo', 'Sicura2024!', 'Matteo'), ('sam', 'Lakeshore2024!', 'Sam')]:
        try:
            conn.execute("INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)",
                         (uname, hash_pw(pw), dname))
        except Exception:
            pass
    conn.commit()
    conn.close()

@app.route('/')
def index():
    return redirect(url_for('kanban') if 'user_id' in session else url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uname = request.form.get('username', '').lower().strip()
        pw = request.form.get('password', '')
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username=? AND password_hash=?',
                            (uname, hash_pw(pw))).fetchone()
        conn.close()
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['display_name'] = user['display_name']
            return redirect(url_for('kanban'))
        return render_template('login.html', error='Invalid credentials.')
    return render_template('login.html', error=None)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/kanban')
def kanban():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('kanban.html', display_name=session['display_name'])

def enrich(conn, row):
    p = dict(row)
    cnt = conn.execute('SELECT COUNT(*) AS c FROM call_logs WHERE prospect_id=?', (p['id'],)).fetchone()['c']
    p['has_contact'] = cnt > 0
    return p

@app.route('/api/prospects', methods=['GET'])
def get_prospects():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    rows = conn.execute('SELECT * FROM prospects ORDER BY created_at ASC').fetchall()
    result = [enrich(conn, r) for r in rows]
    conn.close()
    return jsonify(result)

@app.route('/api/prospects', methods=['POST'])
def create_prospect():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    d = request.json
    conn = get_db()
    cur = conn.execute('''
        INSERT INTO prospects (sponsor_name, plan_name, ein, city, state, industry,
            plan_assets, num_participants, fees_pct_assets, total_fees, fee_tier,
            contact_name, phone, email, mailer_sent_date, stage, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (d.get('sponsor_name'), d.get('plan_name'), d.get('ein'),
          d.get('city'), d.get('state'), d.get('industry'),
          d.get('plan_assets'), d.get('num_participants'),
          d.get('fees_pct_assets'), d.get('total_fees'), d.get('fee_tier'),
          d.get('contact_name'), d.get('phone'), d.get('email'),
          d.get('mailer_sent_date'), d.get('stage', 'Mailer Sent'), d.get('notes')))
    conn.commit()
    row = conn.execute('SELECT * FROM prospects WHERE id=?', (cur.lastrowid,)).fetchone()
    result = enrich(conn, row)
    conn.close()
    return jsonify(result)

UPDATABLE = ['sponsor_name','plan_name','ein','city','state','industry',
             'plan_assets','num_participants','fees_pct_assets','total_fees','fee_tier',
             'contact_name','phone','email','mailer_sent_date','notes','stage']

@app.route('/api/prospects/<int:pid>', methods=['PUT'])
def update_prospect(pid):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    d = request.json
    conn = get_db()
    current = conn.execute('SELECT stage FROM prospects WHERE id=?', (pid,)).fetchone()
    fields, values = [], []
    for f in UPDATABLE:
        if f in d:
            fields.append(f'{f}=?')
            values.append(d[f])
    if 'stage' in d and current and d['stage'] != current['stage']:
        fields.append('stage_entered_at=?')
        values.append(datetime.utcnow().isoformat())
    if fields:
        values.append(pid)
        conn.execute(f'UPDATE prospects SET {", ".join(fields)} WHERE id=?', values)
        conn.commit()
    row = conn.execute('SELECT * FROM prospects WHERE id=?', (pid,)).fetchone()
    result = enrich(conn, row)
    conn.close()
    return jsonify(result)

@app.route('/api/prospects/<int:pid>', methods=['DELETE'])
def delete_prospect(pid):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    conn.execute('DELETE FROM call_logs WHERE prospect_id=?', (pid,))
    conn.execute('DELETE FROM prospects WHERE id=?', (pid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/prospects/<int:pid>/logs', methods=['GET'])
def get_logs(pid):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    logs = conn.execute('SELECT * FROM call_logs WHERE prospect_id=? ORDER BY timestamp DESC', (pid,)).fetchall()
    conn.close()
    return jsonify([dict(l) for l in logs])

@app.route('/api/prospects/<int:pid>/logs', methods=['POST'])
def add_log(pid):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    d = request.json
    note = (d.get('note') or '').strip()
    if not note:
        return jsonify({'error': 'Note required'}), 400
    conn = get_db()
    cur = conn.execute('INSERT INTO call_logs (prospect_id, user_id, display_name, note) VALUES (?,?,?,?)',
                       (pid, session['user_id'], session['display_name'], note))
    conn.commit()
    log = dict(conn.execute('SELECT * FROM call_logs WHERE id=?', (cur.lastrowid,)).fetchone())
    conn.close()
    return jsonify(log)

COLUMN_MAP = {
    'sponsor_name':     ['sponsor name','company','employer name','plan sponsor','business name','company name'],
    'plan_name':        ['plan name','plan','401k plan','retirement plan'],
    'ein':              ['ein','employer id','employer identification number','tax id'],
    'city':             ['city'],
    'state':            ['state'],
    'industry':         ['industry','sector','sic','naics'],
    'plan_assets':      ['plan assets ($)','plan assets','assets','total assets','net assets'],
    'num_participants': ['participants','num participants','number of participants','active participants','total participants'],
    'fees_pct_assets':  ['fees % assets','fees %','fee %','fees percent','fee percent','fee pct'],
    'total_fees':       ['total fees ($)','total fees','total fee','fees','fee amount'],
    'fee_tier':         ['fee tier','tier'],
    'contact_name':     ['contact','contact name','name','owner','plan administrator'],
    'phone':            ['phone','telephone','phone number','tel'],
    'email':            ['email','email address','e-mail'],
    'mailer_sent_date': ['mailer sent','mailer date','mail date','date sent'],
}
SKIP_COLS = {'report type','batch name','date generated','pdf file'}

@app.route('/api/import', methods=['POST'])
def import_csv():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    f = request.files.get('file')
    if not f:
        return jsonify({'error': 'No file'}), 400
    content = f.read().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(content))
    headers_raw = reader.fieldnames or []
    headers_lower = [h.lower().strip() for h in headers_raw]

    def find_col(candidates):
        for i, h in enumerate(headers_lower):
            if h in candidates and h not in SKIP_COLS:
                return headers_raw[i]
        return None

    mapping = {field: find_col(candidates) for field, candidates in COLUMN_MAP.items()}
    conn = get_db()
    count, skipped = 0, 0
    today = datetime.utcnow().strftime('%Y-%m-%d')

    for row in reader:
        def g(field):
            col = mapping.get(field)
            return row.get(col, '').strip() if col else ''

        sponsor = g('sponsor_name')
        if not sponsor or sponsor.upper() in ('SPONSOR NAME','N/A',''):
            skipped += 1
            continue

        def to_float(val):
            try: return float(val.replace(',','').replace('$','').replace('%','')) if val else None
            except: return None

        def to_int(val):
            try: return int(val.replace(',','')) if val else None
            except: return None

        conn.execute('''
            INSERT INTO prospects (sponsor_name, plan_name, ein, city, state, industry,
                plan_assets, num_participants, fees_pct_assets, total_fees, fee_tier,
                contact_name, phone, email, mailer_sent_date)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (sponsor, g('plan_name'), g('ein'), g('city'), g('state'), g('industry'),
              to_float(g('plan_assets')), to_int(g('num_participants')),
              to_float(g('fees_pct_assets')), to_float(g('total_fees')), g('fee_tier'),
              g('contact_name'), g('phone'), g('email'), g('mailer_sent_date') or today))
        count += 1

    conn.commit()
    conn.close()
    return jsonify({'imported': count, 'skipped': skipped})

if __name__ == '__main__':
    init_db()
    app.run(debug=False, host='0.0.0.0', port=5000)
