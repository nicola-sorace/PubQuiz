from flask import Flask, render_template, request, session, abort, redirect, g
import sqlite3
import hashlib, time

app = Flask(__name__)

DATABASE = 'quiz.db'
SECRET_ADMIN_NAME = '_secadmin'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.before_first_request
def init_db():
    db = get_db()
    cur = db.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS players ( name TEXT, score INT, last_seen INT )')
    cur.execute('DELETE FROM players')
    cur.execute('CREATE TABLE IF NOT EXISTS questions ( r_num INT, q_num INT, question TEXT, type TEXT, choices TEXT, answer TEXT )')
    cur.execute('CREATE TABLE IF NOT EXISTS responses ( r_num INT, q_num INT, name TEXT, answer TEXT )')
    cur.execute('CREATE TABLE IF NOT EXISTS state ( r_num INT, q_num INT, done INT )')
    cur.execute('INSERT INTO state (r_num, q_num, done) VALUES (0,0,0) ')
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.route('/quiz_view')
def quiz_view():
    db = get_db()
    cur = db.cursor()
    now_time = int(time.time())

    name = session.get('name', '')
    player = cur.execute('SELECT * FROM players WHERE name=?', (name,)).fetchone()
    if player == None:
        return 'NOLOGIN'
    else:
        cur.execute('UPDATE players SET last_seen=? WHERE name=?', (int(time.time()), name))
        db.commit()
    
    state = cur.execute('SELECT * FROM state').fetchone()
    players = cur.execute('SELECT * FROM players WHERE name!=?', (SECRET_ADMIN_NAME,)).fetchall()
    r_num = state['r_num']
    q_num = state['q_num']

    if r_num == 0: # Quiz not started
        return render_template('quiz_not_started.html', players=players, name=name, now_time=now_time)

    questions = cur.execute('SELECT * FROM questions WHERE r_num=? AND q_num<=? ORDER BY r_num, q_num ASC', (r_num, q_num)).fetchall()
    responses = cur.execute('SELECT * FROM responses WHERE r_num=? AND name=?', (r_num, name)).fetchall()

    if state['done'] == 0: # Active round
        answers = {}
        for r in responses:
            answers[r['q_num']] = r['answer']
        return render_template('quiz_round.html', players=players, name=name, now_time=now_time, r_num=r_num, questions=questions, answers=answers, enumerate=enumerate)
    else: # Completed round
        responses = cur.execute('SELECT * FROM responses WHERE r_num=?', (r_num,)).fetchall()
        org_responses = {} # Group responses into dictionary by question number
        for response in responses:
            q = response['q_num']
            if q not in org_responses:
                org_responses[q] = [response]
            else:
                org_responses[q].append(response)
        return render_template('quiz_round_done.html', players=players, name=name, now_time=now_time, r_num=r_num, questions=questions, responses=org_responses, enumerate=enumerate)

@app.route('/quiz_endpoint', methods=['POST'])
def quiz_endpoint():
    name = session.get('name', '')

    if name == '':
        return abort(403)
    if name == SECRET_ADMIN_NAME:
        return 'ok'

    db = get_db()
    cur = db.cursor()
    r_num = cur.execute('SELECT r_num FROM state').fetchone()[0]
    for param in request.form:
        if param.startswith('ans_'):
            q_num = int(param[4:])
            ans_val = request.form[param]
            r = cur.execute('SELECT * FROM responses WHERE r_num=? AND q_num=? AND name=?', (r_num, q_num, name)).fetchone()
            if r == None:
                cur.execute('INSERT INTO responses (r_num, q_num, name, answer) VALUES (?,?,?,?)', (r_num, q_num, name, ans_val))
            else:
                cur.execute('UPDATE responses SET answer=? WHERE r_num=? AND q_num=? AND name=?', (ans_val, r_num, q_num, name))
    db.commit()
    return 'ok'

@app.route('/control', methods=['GET', 'POST'])
def control():
    db = get_db()
    cur = db.cursor()
    state = cur.execute('SELECT * FROM state').fetchone()

    r_num = int(state['r_num'])
    q_num = int(state['q_num'])
    done = int(state['done'])
    if request.method == 'POST':
        if request.form.get('next') != None:
            print('next')
            if done or r_num == 0:
                next_q = cur.execute('SELECT * FROM questions WHERE r_num=? AND q_num=?', (r_num+1, 1)).fetchone()
                if next_q != None:
                    r_num += 1
                    q_num = 0
                    done = 0
            else:
                next_q = cur.execute('SELECT * FROM questions WHERE r_num=? AND q_num=?', (r_num, q_num+1)).fetchone()
                if next_q != None:
                    q_num += 1
                else:
                    done = 1
        elif request.form.get('prev') != None:
            print('prev')
            if done:
                done = 0
            elif q_num == 0:
                if r_num == 1:
                    r_num = 0
                    q_num = 0
                elif r_num != 0:
                    prev_q = cur.execute('SELECT * FROM questions WHERE r_num=? ORDER BY q_num DESC', (r_num-1, )).fetchone()
                    r_num -= 1
                    q_num = prev_q['q_num']
                    done = 1
            else:
                q_num -= 1


        elif request.form.get('kick_players') != None:
            cur.execute('DELETE FROM players')
        elif request.form.get('reset_state') != None:
            cur.execute('DELETE FROM state')
            cur.execute('DELETE FROM responses')
            r_num = 0
            q_num = 0
            done = 0
            cur.execute('INSERT INTO state (r_num) VALUES (0)')

        cur.execute('UPDATE state SET r_num=?, q_num=?, done=?', (r_num, q_num, done))
        db.commit()

    return render_template('control.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'name' in request.form:
        session['name'] = name = request.form['name']
        db = get_db()
        db.cursor().execute('INSERT INTO players (name, score, admin, last_seen) VALUES (?, 0, ?, ?)', (name, int(name==SECRET_ADMIN_NAME), int(time.time())))
        db.commit()
        return redirect('/', code=302)
    return render_template('login.html')

def new_secret():
    hash = hashlib.sha1()
    hash.update( ('Wubwub' + str(time.time())).encode('utf-8') )
    return hash.hexdigest()

@app.route('/')
def main():

    if not session.get('name'):
        return redirect('/login', code=302)
    name = session['name']
    if name == '_gamemaster':
        # control
        pass
    return render_template('main.html', name=name)

if __name__ == '__main__':
    print(new_secret())
    app.secret_key = new_secret()
    app.run(host='0.0.0.0', port=5000, debug=True)

