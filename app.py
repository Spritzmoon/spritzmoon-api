from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import json
import hashlib
import time
import random
import string
import os
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# Database configuration
DATABASE_PATH = '/tmp/spritzmoon_global.db'

def get_db_connection():
    """Get database connection with proper configuration"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Initialize the database with required tables"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create devices table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            mining_rate REAL NOT NULL,
            balance REAL DEFAULT 0.0,
            last_faucet_claim TEXT,
            last_seen TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')
    
    # Create global blockchain table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS global_blockchain (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            from_address TEXT NOT NULL,
            to_address TEXT NOT NULL,
            amount REAL NOT NULL,
            timestamp TEXT NOT NULL,
            block_number INTEGER NOT NULL
        )
    ''')
    
    # Create mining sessions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mining_sessions (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            earned REAL DEFAULT 0.0,
            mining_rate REAL NOT NULL,
            FOREIGN KEY (device_id) REFERENCES devices (id)
        )
    ''')
    
    # Create global stats table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS global_stats (
            id INTEGER PRIMARY KEY,
            total_blocks INTEGER DEFAULT 1,
            total_users INTEGER DEFAULT 0,
            active_users INTEGER DEFAULT 0,
            total_transactions INTEGER DEFAULT 0,
            total_hash_rate REAL DEFAULT 0.0,
            last_updated TEXT NOT NULL
        )
    ''')
    
    # Initialize genesis block if not exists
    cursor.execute('SELECT COUNT(*) FROM global_blockchain WHERE type = "genesis"')
    if cursor.fetchone()[0] == 0:
        genesis_tx_id = generate_tx_id()
        genesis_time = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT INTO global_blockchain 
            (id, type, from_address, to_address, amount, timestamp, block_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (genesis_tx_id, 'genesis', 'Genesis Block', 'Global Network', 0.0, genesis_time, 1))
    
    # Initialize global stats if not exists
    cursor.execute('SELECT COUNT(*) FROM global_stats')
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO global_stats 
            (total_blocks, total_users, active_users, total_transactions, total_hash_rate, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (1, 0, 0, 1, 0.0, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

def generate_device_id():
    """Generate a unique device ID in SPM format"""
    part1 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    part2 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    part3 = ''.join(random.choices(string.digits, k=2))
    return f"SPM_{part1}_{part2}_{part3}"

def generate_tx_id():
    """Generate a unique transaction ID"""
    return 'TX_' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def calculate_mining_rate(device_id):
    """Calculate mining rate based on device ID"""
    hash_value = hashlib.md5(device_id.encode()).hexdigest()
    rate = (int(hash_value[:8], 16) % 200 + 50) / 100.0  # 0.5 to 2.5 SPM/min
    return round(rate, 2)

def update_global_stats():
    """Update global statistics"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Count total users
    cursor.execute('SELECT COUNT(*) FROM devices')
    total_users = cursor.fetchone()[0]
    
    # Count active users (last seen within 1 hour)
    one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
    cursor.execute('SELECT COUNT(*) FROM devices WHERE last_seen > ?', (one_hour_ago,))
    active_users = cursor.fetchone()[0]
    
    # Count total transactions
    cursor.execute('SELECT COUNT(*) FROM global_blockchain')
    total_transactions = cursor.fetchone()[0]
    
    # Calculate total hash rate (active users * average rate)
    cursor.execute('SELECT AVG(mining_rate) FROM devices WHERE last_seen > ?', (one_hour_ago,))
    avg_rate = cursor.fetchone()[0] or 0
    total_hash_rate = active_users * avg_rate * 1.5  # Convert to TH/s simulation
    
    # Update stats
    cursor.execute('''
        UPDATE global_stats SET 
        total_users = ?, active_users = ?, total_transactions = ?, 
        total_hash_rate = ?, last_updated = ?
        WHERE id = 1
    ''', (total_users, active_users, total_transactions, total_hash_rate, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

@app.route('/api/device/register', methods=['POST'])
def register_device():
    """Register a new device or return existing device info"""
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if device_id:
            # Check if device exists
            cursor.execute('SELECT * FROM devices WHERE id = ?', (device_id,))
            device = cursor.fetchone()
            
            if device:
                # Update last seen
                cursor.execute('UPDATE devices SET last_seen = ? WHERE id = ?', 
                             (datetime.now().isoformat(), device_id))
                conn.commit()
                conn.close()
                
                return jsonify({
                    'success': True,
                    'device_id': device_id,
                    'mining_rate': device['mining_rate'],
                    'balance': device['balance'],
                    'message': 'Device reconnected'
                })
        
        # Generate new device ID
        new_device_id = generate_device_id()
        mining_rate = calculate_mining_rate(new_device_id)
        current_time = datetime.now().isoformat()
        
        # Insert new device
        cursor.execute('''
            INSERT INTO devices (id, mining_rate, balance, last_seen, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (new_device_id, mining_rate, 0.0, current_time, current_time))
        
        # Create registration transaction
        tx_id = generate_tx_id()
        cursor.execute('''
            INSERT INTO global_blockchain 
            (id, type, from_address, to_address, amount, timestamp, block_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (tx_id, 'registration', 'Global Network', new_device_id, 0.0, current_time, 1))
        
        conn.commit()
        conn.close()
        
        # Update global stats
        update_global_stats()
        
        return jsonify({
            'success': True,
            'device_id': new_device_id,
            'mining_rate': mining_rate,
            'balance': 0.0,
            'tx_id': tx_id,
            'message': 'Device registered successfully'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/device/balance', methods=['GET'])
def get_device_balance():
    """Get device balance"""
    try:
        device_id = request.args.get('device_id')
        if not device_id:
            return jsonify({'success': False, 'error': 'Device ID required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT balance FROM devices WHERE id = ?', (device_id,))
        device = cursor.fetchone()
        
        if not device:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        conn.close()
        
        return jsonify({
            'success': True,
            'balance': device['balance']
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/mining/start', methods=['POST'])
def start_mining():
    """Start mining session"""
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        
        if not device_id:
            return jsonify({'success': False, 'error': 'Device ID required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get device info
        cursor.execute('SELECT mining_rate FROM devices WHERE id = ?', (device_id,))
        device = cursor.fetchone()
        
        if not device:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        # Create mining session
        session_id = generate_tx_id()
        start_time = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT INTO mining_sessions (id, device_id, start_time, mining_rate)
            VALUES (?, ?, ?, ?)
        ''', (session_id, device_id, start_time, device['mining_rate']))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'start_time': int(time.time() * 1000),  # JavaScript timestamp
            'mining_rate': device['mining_rate']
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/mining/stop', methods=['POST'])
def stop_mining():
    """Stop mining session and record earnings"""
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        
        if not device_id:
            return jsonify({'success': False, 'error': 'Device ID required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get latest mining session
        cursor.execute('''
            SELECT * FROM mining_sessions 
            WHERE device_id = ? AND end_time IS NULL 
            ORDER BY start_time DESC LIMIT 1
        ''', (device_id,))
        session = cursor.fetchone()
        
        if not session:
            return jsonify({'success': False, 'error': 'No active mining session'}), 404
        
        # Calculate earnings
        start_time = datetime.fromisoformat(session['start_time'])
        end_time = datetime.now()
        duration_minutes = (end_time - start_time).total_seconds() / 60
        earned = duration_minutes * session['mining_rate']
        
        # Update mining session
        cursor.execute('''
            UPDATE mining_sessions 
            SET end_time = ?, earned = ? 
            WHERE id = ?
        ''', (end_time.isoformat(), earned, session['id']))
        
        # Update device balance
        cursor.execute('''
            UPDATE devices 
            SET balance = balance + ?, last_seen = ? 
            WHERE id = ?
        ''', (earned, end_time.isoformat(), device_id))
        
        # Get new balance
        cursor.execute('SELECT balance FROM devices WHERE id = ?', (device_id,))
        new_balance = cursor.fetchone()['balance']
        
        # Create mining transaction
        tx_id = generate_tx_id()
        cursor.execute('''
            INSERT INTO global_blockchain 
            (id, type, from_address, to_address, amount, timestamp, block_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (tx_id, 'mining', 'Mining Reward', device_id, earned, end_time.isoformat(), 1))
        
        conn.commit()
        conn.close()
        
        # Update global stats
        update_global_stats()
        
        return jsonify({
            'success': True,
            'earned': earned,
            'new_balance': new_balance,
            'tx_id': tx_id
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/faucet/claim', methods=['POST'])
def claim_faucet():
    """Claim faucet reward"""
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        
        if not device_id:
            return jsonify({'success': False, 'error': 'Device ID required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check device exists
        cursor.execute('SELECT * FROM devices WHERE id = ?', (device_id,))
        device = cursor.fetchone()
        
        if not device:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        # Check cooldown (24 hours)
        if device['last_faucet_claim']:
            last_claim = datetime.fromisoformat(device['last_faucet_claim'])
            if datetime.now() - last_claim < timedelta(hours=24):
                return jsonify({'success': False, 'error': 'Faucet on cooldown'}), 429
        
        # Award faucet
        faucet_amount = 100.0
        current_time = datetime.now().isoformat()
        
        cursor.execute('''
            UPDATE devices 
            SET balance = balance + ?, last_faucet_claim = ?, last_seen = ? 
            WHERE id = ?
        ''', (faucet_amount, current_time, current_time, device_id))
        
        # Get new balance
        cursor.execute('SELECT balance FROM devices WHERE id = ?', (device_id,))
        new_balance = cursor.fetchone()['balance']
        
        # Create faucet transaction
        tx_id = generate_tx_id()
        cursor.execute('''
            INSERT INTO global_blockchain 
            (id, type, from_address, to_address, amount, timestamp, block_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (tx_id, 'faucet', 'Global Faucet', device_id, faucet_amount, current_time, 1))
        
        conn.commit()
        conn.close()
        
        # Update global stats
        update_global_stats()
        
        return jsonify({
            'success': True,
            'amount': faucet_amount,
            'new_balance': new_balance,
            'tx_id': tx_id
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/transfer', methods=['POST'])
def transfer_spm():
    """Transfer SPM between devices"""
    try:
        data = request.get_json()
        from_device = data.get('from_device')
        to_device = data.get('to_device')
        amount = float(data.get('amount', 0))
        
        if not from_device or not to_device or amount <= 0:
            return jsonify({'success': False, 'error': 'Invalid transfer data'}), 400
        
        if from_device == to_device:
            return jsonify({'success': False, 'error': 'Cannot transfer to yourself'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check sender exists and has sufficient balance
        cursor.execute('SELECT balance FROM devices WHERE id = ?', (from_device,))
        sender = cursor.fetchone()
        
        if not sender:
            return jsonify({'success': False, 'error': 'Sender device not found'}), 404
        
        if sender['balance'] < amount:
            return jsonify({'success': False, 'error': 'Insufficient balance'}), 400
        
        # Check if recipient exists, create if not
        cursor.execute('SELECT id FROM devices WHERE id = ?', (to_device,))
        recipient = cursor.fetchone()
        
        if not recipient:
            # Create recipient device
            mining_rate = calculate_mining_rate(to_device)
            current_time = datetime.now().isoformat()
            
            cursor.execute('''
                INSERT INTO devices (id, mining_rate, balance, last_seen, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (to_device, mining_rate, 0.0, current_time, current_time))
        
        # Perform transfer
        current_time = datetime.now().isoformat()
        
        cursor.execute('''
            UPDATE devices 
            SET balance = balance - ?, last_seen = ? 
            WHERE id = ?
        ''', (amount, current_time, from_device))
        
        cursor.execute('''
            UPDATE devices 
            SET balance = balance + ?, last_seen = ? 
            WHERE id = ?
        ''', (amount, current_time, to_device))
        
        # Get new balances
        cursor.execute('SELECT balance FROM devices WHERE id = ?', (from_device,))
        sender_new_balance = cursor.fetchone()['balance']
        
        cursor.execute('SELECT balance FROM devices WHERE id = ?', (to_device,))
        recipient_new_balance = cursor.fetchone()['balance']
        
        # Create transfer transaction
        tx_id = generate_tx_id()
        cursor.execute('''
            INSERT INTO global_blockchain 
            (id, type, from_address, to_address, amount, timestamp, block_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (tx_id, 'transfer', from_device, to_device, amount, current_time, 1))
        
        conn.commit()
        conn.close()
        
        # Update global stats
        update_global_stats()
        
        return jsonify({
            'success': True,
            'tx_id': tx_id,
            'sender_new_balance': sender_new_balance,
            'recipient_new_balance': recipient_new_balance
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/blockchain/transactions', methods=['GET'])
def get_transactions():
    """Get all blockchain transactions"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, type, from_address as "from", to_address as "to", 
                   amount, timestamp 
            FROM global_blockchain 
            ORDER BY timestamp DESC
        ''')
        
        transactions = []
        for row in cursor.fetchall():
            transactions.append({
                'id': row['id'],
                'type': row['type'],
                'from': row['from'],
                'to': row['to'],
                'amount': row['amount'],
                'timestamp': row['timestamp']
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'transactions': transactions
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/blockchain/stats', methods=['GET'])
def get_blockchain_stats():
    """Get blockchain statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Update stats before returning
        update_global_stats()
        
        cursor.execute('SELECT * FROM global_stats WHERE id = 1')
        stats = cursor.fetchone()
        
        conn.close()
        
        if not stats:
            return jsonify({'success': False, 'error': 'Stats not found'}), 404
        
        return jsonify({
            'success': True,
            'stats': {
                'total_blocks': stats['total_blocks'],
                'total_users': stats['total_users'],
                'active_users': stats['active_users'],
                'total_transactions': stats['total_transactions'],
                'total_hash_rate': stats['total_hash_rate']
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/blockchain/explorer', methods=['GET'])
def blockchain_explorer():
    """Get blockchain explorer data"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get recent transactions
        cursor.execute('''
            SELECT id, type, from_address, to_address, amount, timestamp 
            FROM global_blockchain 
            ORDER BY timestamp DESC 
            LIMIT 50
        ''')
        
        transactions = []
        for row in cursor.fetchall():
            transactions.append({
                'tx_id': row['id'],
                'type': row['type'],
                'from': row['from_address'],
                'to': row['to_address'],
                'amount': row['amount'],
                'timestamp': row['timestamp']
            })
        
        # Get top miners
        cursor.execute('''
            SELECT device_id, SUM(earned) as total_earned, COUNT(*) as sessions
            FROM mining_sessions 
            WHERE earned > 0
            GROUP BY device_id 
            ORDER BY total_earned DESC 
            LIMIT 10
        ''')
        
        top_miners = []
        for row in cursor.fetchall():
            top_miners.append({
                'device_id': row['device_id'],
                'total_earned': row['total_earned'],
                'sessions': row['sessions']
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'transactions': transactions,
            'top_miners': top_miners
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    # Initialize database
    init_database()
    
    # Start the server
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)





