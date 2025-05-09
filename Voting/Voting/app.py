from flask import Flask, render_template, request, redirect, session, url_for
from flask_compress import Compress
import serial
import serial.tools.list_ports
import threading
import time
import hashlib
import json
from datetime import datetime
from serial.serialutil import SerialException

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change this to a strong secret key
Compress(app)  # Enable Gzip compression
app.static_folder = 'static'

# In-memory data stores
users = {'Ranaprathap.G': '', 'Chandru.J': '', 'Sinraj.G': '', 'Harish.MD': ''}
voted_users = set()
candidates = ['Candidate A', 'Candidate B']
votes = {cand: 0 for cand in candidates}

# Blockchain implementation with validity caching
class Block:
    def __init__(self, index, timestamp, data, previous_hash):
        self.index = index
        self.timestamp = timestamp
        self.data = data
        self.previous_hash = previous_hash
        self.hash = self.calculate_hash()

    def calculate_hash(self):
        block_string = json.dumps({
            "index": self.index,
            "timestamp": str(self.timestamp),
            "data": self.data,
            "previous_hash": self.previous_hash
        }, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

class Blockchain:
    def __init__(self):
        self.chain = [self.create_genesis_block()]
        self._is_valid = True  # Cache validity

    def create_genesis_block(self):
        return Block(0, datetime.now(), "Genesis Block", "0")

    def get_latest_block(self):
        return self.chain[-1]

    def add_block(self, new_block_data):
        latest_block = self.get_latest_block()
        new_block = Block(
            index=latest_block.index + 1,
            timestamp=datetime.now(),
            data=new_block_data,
            previous_hash=latest_block.hash
        )
        self.chain.append(new_block)
        self._is_valid = self.is_chain_valid()  # Update cache

    def is_chain_valid(self):
        if self._is_valid:
            return True
        for i in range(1, len(self.chain)):
            current_block = self.chain[i]
            previous_block = self.chain[i-1]
            if current_block.hash != current_block.calculate_hash():
                self._is_valid = False
                return False
            if current_block.previous_hash != previous_block.hash:
                self._is_valid = False
                return False
        self._is_valid = True
        return True

# Initialize blockchain
blockchain = Blockchain()

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
    retry_delay = 5  # Initial retry delay in seconds
    max_retry_delay = 30  # Maximum retry delay
    port_name = 'COM3'  # Serial port
    max_attempts_per_minute = 12  # Limit reconnection attempts
    attempt_count = 0
    last_reset = time.time()

    while True:
        try:
            # Reset attempt count every minute
            current_time = time.time()
            if current_time - last_reset >= 60:
                attempt_count = 0
                last_reset = current_time

            # Check if max attempts reached
            if attempt_count >= max_attempts_per_minute:
                print(f"Max reconnection attempts reached for {port_name}. Waiting 60 seconds.")
                time.sleep(60)
                attempt_count = 0
                last_reset = time.time()
                continue

            # Verify port exists
            available_ports = [port.device for port in serial.tools.list_ports.comports()]
            if port_name not in available_ports:
                print(f"Port {port_name} not found. Available ports: {available_ports}")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)
                continue

            # Initialize serial connection if not exists
            if rfid_serial is None or not rfid_serial.is_open:
                try:
                    rfid_serial = serial.Serial(port_name, 9600, timeout=1)
                    print(f"RFID reader connected on {port_name}")
                    time.sleep(3)  # Stabilization delay
                    retry_delay = 5  # Reset retry delay
                except SerialException as e:
                    print(f"Failed to connect to RFID reader on {port_name}: {e}")
                    rfid_serial = None
                    attempt_count += 1
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, max_retry_delay)
                    continue

            # Check for data
            if rfid_serial.in_waiting == 0:
                time.sleep(0.1)  # Reduce CPU usage
                continue

            # Read data
            try:
                data = rfid_serial.read().decode('utf-8').strip()
                print(f"RFID read: {data}")
                if data in voter_map:
                    name, status = voter_map[data]
                    with rfid_lock:
                        rfid_voter["user"] = name
                        rfid_voter["status"] = status
                    print(f"RFID matched: {name} - {status}")
            except UnicodeDecodeError:
                print("Received invalid data from RFID reader")
                continue
            except SerialException as e:
                print(f"Serial read error: {e}")
                raise  # Re-raise to trigger cleanup

        except SerialException as e:
            print(f"Serial error: {e}")
            if rfid_serial and rfid_serial.is_open:
                try:
                    rfid_serial.close()
                    print(f"Closed {port_name}")
                except Exception as close_err:
                    print(f"Error closing serial port: {close_err}")
            rfid_serial = None
            attempt_count += 1
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max_retry_delay)
        except Exception as e:
            print(f"Unexpected error in RFID thread: {e}")
            time.sleep(1)

# Start RFID listener thread
rfid_thread = threading.Thread(target=read_rfid)
rfid_thread.daemon = True
rfid_thread.start()

# Routes
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
        vote_data = {
            'voter': username,
            'candidate': candidate,
            'timestamp': str(datetime.now())
        }
        blockchain.add_block(vote_data)
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

@app.route('/results_data')
def results_data():
    return {"results": render_template_string(
        "{% for cand, count in votes.items() %}{{ cand }}: {{ count }}<br>{% endfor %}",
        votes=votes)}

@app.route('/admin')
def admin():
    if 'admin' not in session:
        return redirect('/')
    displayed_chain = blockchain.chain[-10:] if len(blockchain.chain) > 10 else blockchain.chain
    return render_template('admin.html',
                         candidates=candidates,
                         votes=votes,
                         total_votes=sum(votes.values()),
                         blockchain=displayed_chain)

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
    global votes, voted_users, blockchain
    votes = {cand: 0 for cand in candidates}
    voted_users = set()
    blockchain = Blockchain()
    return redirect('/admin')

@app.route('/verify_chain')
def verify_chain():
    if 'admin' not in session:
        return redirect('/')
    is_valid = blockchain.is_chain_valid()
    return render_template('message.html',
                        message=f"Blockchain is {'valid' if is_valid else 'invalid'}",
                        icon="check-circle-fill" if is_valid else "x-circle-fill",
                        color="green" if is_valid else "red")

@app.route('/logout')
def logout():
    global rfid_voter, rfid_serial
    # Clear session
    session.clear()
    # Reset RFID voter data
    with rfid_lock:
        rfid_voter["user"] = None
        rfid_voter["status"] = None
        print("RFID voter data reset on logout")
    # Flush serial input buffer to clear pending data
    with rfid_lock:
        if rfid_serial is not None and rfid_serial.is_open:
            try:
                rfid_serial.flushInput()
                print("Serial input buffer flushed on logout")
            except SerialException as e:
                print(f"Error flushing serial buffer on logout: {e}")
    print("User logged out")
    return redirect('/')

@app.route('/static/<path:filename>')
def static_files(filename):
    response = app.send_static_file(filename)
    response.headers['Cache-Control'] = 'public, max-age=31536000'  # Cache for 1 year
    return response

# Serial port cleanup
def cleanup_serial():
    global rfid_serial
    if rfid_serial is not None and rfid_serial.is_open:
        try:
            rfid_serial.close()
            print("Serial port closed during cleanup")
        except Exception as e:
            print(f"Error during serial port cleanup: {e}")

import atexit
atexit.register(cleanup_serial)

if __name__ == '__main__':
    # For production, use gunicorn or waitress:
    # gunicorn -w 4 -b 0.0.0.0:5000 app:app
    # waitress-serve --host 0.0.0.0 --port 5000 app:app
    app.run(debug=False, host='0.0.0.0', threaded=True)