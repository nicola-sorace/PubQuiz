from flask import Flask, render_template, request, session, abort, redirect, g
import logging
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
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    db = get_db()
    cur = db.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS players ( name TEXT, score INT, last_seen INT )')
    cur.execute('DELETE FROM players')
    cur.execute('CREATE TABLE IF NOT EXISTS questions ( r_num INT, q_num INT, question TEXT, type TEXT, choices TEXT, answer TEXT, score INT )')
    cur.execute('CREATE TABLE IF NOT EXISTS responses ( r_num INT, q_num INT, name TEXT, answer TEXT, score INT, hidden INT )')
    cur.execute('CREATE TABLE IF NOT EXISTS state ( r_num INT, q_num INT, done INT )')
    state = cur.execute('SELECT * FROM state').fetchone()
    if state == None:
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
    players = cur.execute('SELECT * FROM players WHERE name!=? ORDER BY score DESC', (SECRET_ADMIN_NAME,)).fetchall()
    r_num = state['r_num']
    q_num = state['q_num']

    if r_num == 0: # Quiz not started
        return render_template('quiz_not_started.html', players=players, name=name, now_time=now_time)

    questions = cur.execute('SELECT * FROM questions WHERE r_num=? AND q_num<=? ORDER BY r_num, q_num ASC', (r_num, q_num)).fetchall()
    questions = [ dict(question) for question in questions ]
    for question in questions:
        question['first_answer'] = question['answer'].split(',')[0]
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
        return render_template('quiz_round_done.html', players=players, name=name, now_time=now_time, r_num=r_num, questions=questions, responses=org_responses, state=state, enumerate=enumerate, len=len)

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
            response = cur.execute('SELECT * FROM responses WHERE r_num=? AND q_num=? AND name=?', (r_num, q_num, name)).fetchone()

            # Only update response if it is new
            if response == None or response['answer'] != ans_val:
                # Auto-score new answer
                score = 0
                question = cur.execute('SELECT * FROM questions WHERE r_num=? AND q_num=?', (r_num, q_num)).fetchone()
                for right_answer in question['answer'].split(','):
                    if ans_val.lower() == right_answer.lower():
                        score = question['score']
                        break

                # Commit response
                if response == None:
                    cur.execute('INSERT INTO responses (r_num, q_num, name, answer, score, hidden) VALUES (?,?,?,?,?,1)', (r_num, q_num, name, ans_val, score))
                else:
                    cur.execute('UPDATE responses SET answer=?, score=? WHERE r_num=? AND q_num=? AND name=?', (ans_val, score, r_num, q_num, name))
                db.commit()
    return 'ok'

def update_scores():
    db = get_db()
    cur = db.cursor()
    players = cur.execute('SELECT name FROM players').fetchall()
    for player in players:
        score = cur.execute('SELECT SUM(score) FROM responses WHERE name=? AND hidden=0', (player['name'],)).fetchone()[0]
        if score == None:
            score = 0
        cur.execute('UPDATE players SET score=? WHERE name=?', (score, player['name']))
    db.commit()


@app.route('/control', methods=['GET', 'POST'])
def control():
    db = get_db()
    cur = db.cursor()
    state = cur.execute('SELECT * FROM state').fetchone()

    r_num = int(state['r_num'])
    q_num = int(state['q_num'])
    done = int(state['done'])
    # Done=1: About to reveal answer (suspense); Done=2: Answer revealed

    if request.method == 'POST':
        if request.form.get('next') != None:
            # Move quiz forward
            next_q = cur.execute('SELECT * FROM questions WHERE r_num=? AND q_num=?', (r_num, q_num+1)).fetchone()
            if done == 1 and q_num > 0:
                # Reveal answer
                done = 2;
                # Unhide response scores
                cur.execute('UPDATE responses SET hidden=0 WHERE r_num<=? AND q_num<=?', (r_num, q_num))
                # We update scores here to show new points only when answer is revealed
                update_scores()
            elif next_q != None:
                # Next question
                q_num += 1
                if done == 2:
                    # Move to next answer but don't reveal yet
                    done = 1
            else:
                if not done and r_num > 0:
                    # Round done; Start going through answers
                    done = 1
                    q_num = 0
                else:
                    # Next round
                    next_q = cur.execute('SELECT * FROM questions WHERE r_num=? AND q_num=?', (r_num+1, 1)).fetchone()
                    if next_q != None:
                        r_num += 1
                        q_num = 0
                        done = 0

        elif request.form.get('prev') != None:
            # Move quiz backwards
            prev_q = cur.execute('SELECT * FROM questions WHERE r_num=? AND q_num=?', (r_num, q_num-1)).fetchone()
            if done == 2:
                done = 1
            elif prev_q != None or q_num == 1:
                # Previous question or restart round
                q_num -= 1
                if done:
                    if q_num != 0:
                        # Last answer is already revealed
                        done = 2
                    else:
                        # Restart round
                        done = 1
            else:
                if done:
                    # Reopen round
                    prev_q = cur.execute('SELECT * FROM questions WHERE r_num=? ORDER BY q_num DESC', (r_num, )).fetchone()
                    done = 0
                    q_num = prev_q['q_num']
                else:
                    if r_num <= 1:
                        # Back to waiting for quiz to start
                        r_num = 0
                    else:
                        # Back to previous round's answers
                        prev_q = cur.execute('SELECT * FROM questions WHERE r_num=? ORDER BY q_num DESC', (r_num-1, )).fetchone()
                        done = 2
                        r_num -= 1
                        q_num = prev_q['q_num']

        elif request.form.get('kick_players') != None:
            cur.execute('DELETE FROM players')
        elif request.form.get('reset_state') != None:
            cur.execute('DELETE FROM state')
            r_num = 0
            q_num = 0
            done = 0
            cur.execute('INSERT INTO state (r_num) VALUES (0)')
        elif request.form.get('reset_responses') != None:
            cur.execute('DELETE FROM responses')
            update_scores()

        cur.execute('UPDATE state SET r_num=?, q_num=?, done=?', (r_num, q_num, done))
        db.commit()

    if done and q_num > 0:
        # Show question-scoring tools
        responses = cur.execute('SELECT * FROM responses WHERE r_num=? AND q_num=?', (r_num, q_num)).fetchall()
        max_score = cur.execute('SELECT score FROM questions WHERE r_num=? AND q_num=?', (r_num, q_num)).fetchone()[0]
    else:
        responses = None
        max_score = None

    if request.method == 'POST' and request.form.get('update_scores'):
        for response in responses:
            name = response['name']
            score = request.form['resp_'+name]
            cur.execute('UPDATE responses SET score=? WHERE r_num=? AND q_num=? AND name=?', (score, r_num, q_num, name))
        db.commit()

        if done == 2:
            # Only update scores now if answer is already revealed
            update_scores()

        # Update responses so that control page shows the right scores
        responses = cur.execute('SELECT * FROM responses WHERE r_num=? AND q_num=?', (r_num, q_num)).fetchall()

    return render_template('control.html', responses=responses, max_score=max_score)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'name' in request.form:
        name = request.form['name']

        db = get_db()
        player = db.cursor().execute('SELECT * FROM players WHERE name=?', (name,)).fetchone()
        if player == None or (time.time() - player['last_seen']) > 4 or name == session.get('name'):
            # Player name is available, login
            print('Login from', request.remote_addr, 'as', name)
            if player == None:
                # If the name is new, create a new player
                db.cursor().execute('INSERT INTO players (name, score, last_seen) VALUES (?, 0, ?)', (name, int(time.time())))
                db.commit()
            session['name'] = name
            return redirect('/', code=302)
        else:
            # Player name is taken
            return 'This user is already logged in!'
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
    app.secret_key = new_secret()
    app.run(host='0.0.0.0', port=5000, debug=True)

