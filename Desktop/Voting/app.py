from flask import Flask, render_template, request, redirect, session, url_for
import serial
import threading
import time
from serial.serialutil import SerialException

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change this to a strong secret key

# Configure static folder
app.static_folder = 'static'

# In-memory data stores
users = {'Ranaprathap.G': '', 'Chandru.J': '', 'Sinraj.G': '', 'Harish.MD': ''}
voted_users = set()
candidates = ['Candidate A', 'Candidate B']
votes = {cand: 0 for cand in candidates}

# RFID data store with thread locking
rfid_voter = {"user": None, "status": None}
rfid_serial = None
rfid_lock = threading.Lock()

# RFID serial reader thread
def read_rfid():
    global rfid_voter, rfid_serial
    voter_map = {
        'R': ("Ranaprathap.G", "Access for Vote"),
        'r': ("Ranaprathap.G", "Already Voted"),
        'C': ("Chandru.J", "Access for Vote"),
        'c': ("Chandru.J", "Already Voted"),
        'S': ("Sinraj.G", "Access for Vote"),
        's': ("Sinraj.G", "Already Voted"),
        'H': ("Harish.MD", "Access for Vote"),
        'h': ("Harish.MD", "Already Voted"),
    }
    
    while True:
        try:
            # Initialize serial connection if not exists
            if rfid_serial is None:
                try:
                    rfid_serial = serial.Serial('COM3', 9600, timeout=1)
                    print("RFID reader connected on COM3")
                    time.sleep(2)  # Allow time for connection to stabilize
                except SerialException as e:
                    print(f"Failed to connect to RFID reader: {e}")
                    rfid_serial = None
                    time.sleep(5)
                    continue
            
            # Read data if available
            if rfid_serial.in_waiting > 0:
                data = rfid_serial.read().decode('utf-8').strip()
                print(f"RFID read: {data}")
                
                if data in voter_map:
                    name, status = voter_map[data]
                    with rfid_lock:
                        rfid_voter["user"] = name
                        rfid_voter["status"] = status
                    print(f"RFID matched: {name} - {status}")
                
        except SerialException as e:
            print(f"Serial error: {e}")
            if rfid_serial:
                try:
                    rfid_serial.close()
                except:
                    pass
            rfid_serial = None
            time.sleep(5)  # Wait before retrying
        except UnicodeDecodeError:
            print("Received invalid data from RFID reader")
            time.sleep(1)
        except Exception as e:
            print(f"Unexpected error in RFID thread: {e}")
            time.sleep(1)

# Start RFID listener thread
rfid_thread = threading.Thread(target=read_rfid)
rfid_thread.daemon = True
rfid_thread.start()

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    if username == 'admin' and password == '1234':
        session['admin'] = True
        return redirect('/admin')
    elif username in users:
        if username in voted_users:
            return render_template('message.html', 
                                message="You have already voted!",
                                icon="exclamation-triangle-fill",
                                color="red")
        session['user'] = username
        return redirect('/dashboard')
    else:
        return render_template('message.html', 
                            message="Invalid credentials",
                            icon="x-circle-fill",
                            color="red")

@app.route('/rfid_login', methods=['GET'])
def rfid_login():
    global rfid_voter

    with rfid_lock:
        current_voter = rfid_voter["user"]
        current_status = rfid_voter["status"]
        rfid_voter["user"] = None  # Reset after reading
    
    if not current_voter:
        return render_template('message.html', 
                            message="Waiting for RFID scan...",
                            icon="hourglass",
                            color="blue")
    
    if current_status == "Access for Vote":
        if current_voter in voted_users:
            return render_template('message.html', 
                                message=f"{current_voter} has already voted!",
                                icon="exclamation-triangle-fill",
                                color="red")
        session['user'] = current_voter
        return redirect('/dashboard')
    else:
        return render_template('message.html', 
                            message=f"{current_voter} has already voted!",
                            icon="exclamation-triangle-fill",
                            color="red")

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect('/')
    return render_template('dashboard.html', 
                         candidates=candidates,
                         username=session['user'])

@app.route('/vote', methods=['POST'])
def vote():
    if 'user' not in session:
        return redirect('/')
    
    candidate = request.form['candidate']
    username = session['user']
    
    if username not in voted_users:
        votes[candidate] += 1
        voted_users.add(username)
        return render_template('message.html', 
                            message=f"Thanks for voting for {candidate}!",
                            icon="check-circle-fill",
                            color="green")
    else:
        return render_template('message.html', 
                            message="You have already voted!",
                            icon="exclamation-triangle-fill",
                            color="red")

@app.route('/results')
def results():
    return render_template('results.html', 
                         votes=votes,
                         total_votes=sum(votes.values()))

@app.route('/admin')
def admin():
    if 'admin' not in session:
        return redirect('/')
    return render_template('admin.html', 
                         candidates=candidates,
                         votes=votes,
                         total_votes=sum(votes.values()))

@app.route('/add_candidate', methods=['POST'])
def add_candidate():
    if 'admin' not in session:
        return redirect('/')
    
    new_cand = request.form['new_candidate'].strip()
    if new_cand and new_cand not in candidates:
        candidates.append(new_cand)
        votes[new_cand] = 0
    return redirect('/admin')

@app.route('/reset_votes', methods=['POST'])
def reset_votes():
    if 'admin' not in session:
        return redirect('/')
    
    global votes, voted_users
    votes = {cand: 0 for cand in candidates}
    voted_users = set()
    return redirect('/admin')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

def cleanup_serial():
    if rfid_serial and rfid_serial.is_open:
        rfid_serial.close()

import atexit
atexit.register(cleanup_serial)

if __name__ == '__main__':
    try:
        app.run(debug=True, host='0.0.0.0')
    finally:
        cleanup_serial()
