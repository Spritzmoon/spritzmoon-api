from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import json
import hashlib
import time
import uuid
import os
from datetime import datetime, timedelta
import threading
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, origins="*")

# Database configuration with absolute path
DATABASE_PATH = '/tmp/spritzmoon_persistent.db'
BACKUP_DATABASE_PATH = '/tmp/spritzmoon_backup.db'

# Global variables for blockchain state
blockchain_lock = threading.Lock()
last_backup_time = time.time()
BACKUP_INTERVAL = 300  # 5 minutes

def init_database():
    """Initialize database with enhanced persistence and backup"""
    try:
        # Create main database
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Create users table with enhanced fields
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                device_id TEXT PRIMARY KEY,
                balance REAL DEFAULT 0.0,
                mining_rate REAL DEFAULT 0.1,
                last_faucet_claim TEXT,
                registration_time TEXT,
                last_activity TEXT,
                total_mined REAL DEFAULT 0.0,
                total_sent REAL DEFAULT 0.0,
                total_received REAL DEFAULT 0.0,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # Create transactions table with enhanced tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                from_device TEXT,
                to_device TEXT,
                amount REAL DEFAULT 0.0,
                timestamp TEXT NOT NULL,
                block_hash TEXT,
                status TEXT DEFAULT 'confirmed',
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create blockchain_blocks table for complete blockchain tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blockchain_blocks (
                block_number INTEGER PRIMARY KEY,
                block_hash TEXT UNIQUE NOT NULL,
                previous_hash TEXT,
                timestamp TEXT NOT NULL,
                transactions_count INTEGER DEFAULT 0,
                merkle_root TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create mining_sessions table for detailed mining tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mining_sessions (
                session_id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_seconds INTEGER DEFAULT 0,
                tokens_earned REAL DEFAULT 0.0,
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create system_stats table for global statistics
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_stats (
                stat_name TEXT PRIMARY KEY,
                stat_value TEXT NOT NULL,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create indexes for better performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_transactions_device ON transactions(from_device, to_device)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_activity ON users(last_activity)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_mining_device ON mining_sessions(device_id)')
        
        # Initialize genesis block if not exists
        cursor.execute('SELECT COUNT(*) FROM blockchain_blocks')
        if cursor.fetchone()[0] == 0:
            genesis_hash = hashlib.sha256(b'SpritzMoon Genesis Block').hexdigest()
            cursor.execute('''
                INSERT INTO blockchain_blocks 
                (block_number, block_hash, previous_hash, timestamp, transactions_count, merkle_root)
                VALUES (0, ?, 'genesis', ?, 1, ?)
            ''', (genesis_hash, datetime.now().isoformat(), genesis_hash))
            
            # Add genesis transaction
            genesis_tx_id = str(uuid.uuid4())
            cursor.execute('''
                INSERT INTO transactions 
                (id, type, from_device, to_device, amount, timestamp, block_hash, metadata)
                VALUES (?, 'genesis', 'system', 'blockchain', 0.0, ?, ?, ?)
            ''', (genesis_tx_id, datetime.now().isoformat(), genesis_hash, 
                  json.dumps({'description': 'SpritzMoon Genesis Block'})))
        
        # Initialize system stats
        stats = [
            ('total_blocks', '1'),
            ('total_users', '0'),
            ('total_transactions', '1'),
            ('total_hash_rate', '0.0'),
            ('network_start_time', datetime.now().isoformat())
        ]
        
        for stat_name, stat_value in stats:
            cursor.execute('''
                INSERT OR IGNORE INTO system_stats (stat_name, stat_value)
                VALUES (?, ?)
            ''', (stat_name, stat_value))
        
        conn.commit()
        conn.close()
        
        # Create backup
        create_database_backup()
        
        logger.info("Database initialized successfully with enhanced persistence")
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

def create_database_backup():
    """Create a backup of the database"""
    try:
        if os.path.exists(DATABASE_PATH):
            import shutil
            shutil.copy2(DATABASE_PATH, BACKUP_DATABASE_PATH)
            logger.info("Database backup created successfully")
    except Exception as e:
        logger.error(f"Failed to create database backup: {e}")

def restore_from_backup():
    """Restore database from backup if main database is corrupted"""
    try:
        if os.path.exists(BACKUP_DATABASE_PATH):
            import shutil
            shutil.copy2(BACKUP_DATABASE_PATH, DATABASE_PATH)
            logger.info("Database restored from backup")
            return True
    except Exception as e:
        logger.error(f"Failed to restore from backup: {e}")
    return False

def get_db_connection():
    """Get database connection with error handling and backup restoration"""
    try:
        conn = sqlite3.connect(DATABASE_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Test connection
        conn.execute('SELECT 1').fetchone()
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        # Try to restore from backup
        if restore_from_backup():
            try:
                conn = sqlite3.connect(DATABASE_PATH, timeout=30.0)
                conn.row_factory = sqlite3.Row
                return conn
            except Exception as e2:
                logger.error(f"Failed to connect after backup restore: {e2}")
        raise

def update_system_stats():
    """Update global system statistics"""
    try:
        with blockchain_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Count total blocks
            cursor.execute('SELECT COUNT(*) FROM blockchain_blocks')
            total_blocks = cursor.fetchone()[0]
            
            # Count total users
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]
            
            # Count active users (activity in last 24 hours)
            yesterday = (datetime.now() - timedelta(days=1)).isoformat()
            cursor.execute('SELECT COUNT(*) FROM users WHERE last_activity > ?', (yesterday,))
            active_users = cursor.fetchone()[0]
            
            # Count total transactions
            cursor.execute('SELECT COUNT(*) FROM transactions')
            total_transactions = cursor.fetchone()[0]
            
            # Calculate total hash rate (simplified)
            cursor.execute('SELECT COUNT(*) FROM mining_sessions WHERE status = "active"')
            active_miners = cursor.fetchone()[0]
            total_hash_rate = active_miners * 0.5  # 0.5 TH/s per active miner
            
            # Update stats
            stats_updates = [
                ('total_blocks', str(total_blocks)),
                ('total_users', str(total_users)),
                ('active_users', str(active_users)),
                ('total_transactions', str(total_transactions)),
                ('total_hash_rate', str(total_hash_rate)),
                ('last_stats_update', datetime.now().isoformat())
            ]
            
            for stat_name, stat_value in stats_updates:
                cursor.execute('''
                    INSERT OR REPLACE INTO system_stats (stat_name, stat_value, last_updated)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (stat_name, stat_value))
            
            conn.commit()
            conn.close()
            
    except Exception as e:
        logger.error(f"Failed to update system stats: {e}")

def add_transaction_to_blockchain(tx_type, from_device, to_device, amount, metadata=None):
    """Add transaction to blockchain with complete persistence"""
    try:
        with blockchain_lock:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Generate transaction ID
            tx_id = str(uuid.uuid4())
            timestamp = datetime.now().isoformat()
            
            # Get current block number
            cursor.execute('SELECT MAX(block_number) FROM blockchain_blocks')
            result = cursor.fetchone()
            current_block = result[0] if result[0] is not None else 0
            
            # Create new block if needed (every 10 transactions)
            cursor.execute('SELECT COUNT(*) FROM transactions WHERE block_hash IS NOT NULL')
            tx_count = cursor.fetchone()[0]
            
            if tx_count % 10 == 0 and tx_count > 0:
                # Create new block
                new_block_number = current_block + 1
                cursor.execute('SELECT block_hash FROM blockchain_blocks WHERE block_number = ?', (current_block,))
                previous_hash = cursor.fetchone()[0]
                
                # Generate new block hash
                block_data = f"{new_block_number}{previous_hash}{timestamp}"
                new_block_hash = hashlib.sha256(block_data.encode()).hexdigest()
                
                cursor.execute('''
                    INSERT INTO blockchain_blocks 
                    (block_number, block_hash, previous_hash, timestamp, transactions_count)
                    VALUES (?, ?, ?, ?, 1)
                ''', (new_block_number, new_block_hash, previous_hash, timestamp))
                
                block_hash = new_block_hash
            else:
                # Use current block
                cursor.execute('SELECT block_hash FROM blockchain_blocks WHERE block_number = ?', (current_block,))
                block_hash = cursor.fetchone()[0]
                
                # Update transaction count
                cursor.execute('''
                    UPDATE blockchain_blocks 
                    SET transactions_count = transactions_count + 1 
                    WHERE block_number = ?
                ''', (current_block,))
            
            # Add transaction
            cursor.execute('''
                INSERT INTO transactions 
                (id, type, from_device, to_device, amount, timestamp, block_hash, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (tx_id, tx_type, from_device, to_device, amount, timestamp, block_hash, 
                  json.dumps(metadata) if metadata else None))
            
            conn.commit()
            conn.close()
            
            # Update system stats
            update_system_stats()
            
            # Create backup periodically
            global last_backup_time
            if time.time() - last_backup_time > BACKUP_INTERVAL:
                create_database_backup()
                last_backup_time = time.time()
            
            logger.info(f"Transaction added to blockchain: {tx_id}")
            return tx_id
            
    except Exception as e:
        logger.error(f"Failed to add transaction to blockchain: {e}")
        return None

@app.route('/')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'SpritzMoon Blockchain API',
        'version': '2.0.0',
        'timestamp': datetime.now().isoformat(),
        'database_status': 'connected'
    })

@app.route('/api/device/register', methods=['POST'])
def register_device():
    """Register a new device or reconnect existing device"""
    try:
        data = request.get_json() or {}
        existing_device_id = data.get('device_id')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if existing_device_id:
            # Check if device exists
            cursor.execute('SELECT * FROM users WHERE device_id = ?', (existing_device_id,))
            user = cursor.fetchone()
            
            if user:
                # Update last activity
                cursor.execute('''
                    UPDATE users SET last_activity = ?, is_active = 1 
                    WHERE device_id = ?
                ''', (datetime.now().isoformat(), existing_device_id))
                conn.commit()
                conn.close()
                
                return jsonify({
                    'success': True,
                    'device_id': existing_device_id,
                    'balance': user['balance'],
                    'mining_rate': user['mining_rate'],
                    'message': 'Device reconnected successfully'
                })
        
        # Generate new device ID
        device_id = f"SPM_{uuid.uuid4().hex[:8].upper()}_{uuid.uuid4().hex[:6].upper()}_{uuid.uuid4().hex[:2].upper()}"
        mining_rate = round(0.05 + (hash(device_id) % 100) / 1000, 3)  # 0.05-0.15 SPM/min
        
        # Insert new user
        cursor.execute('''
            INSERT INTO users 
            (device_id, balance, mining_rate, registration_time, last_activity)
            VALUES (?, 0.0, ?, ?, ?)
        ''', (device_id, mining_rate, datetime.now().isoformat(), datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        # Add registration transaction to blockchain
        add_transaction_to_blockchain('registration', 'system', device_id, 0.0, 
                                    {'action': 'device_registration', 'mining_rate': mining_rate})
        
        logger.info(f"New device registered: {device_id}")
        
        return jsonify({
            'success': True,
            'device_id': device_id,
            'balance': 0.0,
            'mining_rate': mining_rate,
            'message': 'Device registered successfully'
        })
        
    except Exception as e:
        logger.error(f"Device registration failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/device/balance')
def get_balance():
    """Get device balance"""
    try:
        device_id = request.args.get('device_id')
        if not device_id:
            return jsonify({'success': False, 'error': 'Device ID required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT balance FROM users WHERE device_id = ?', (device_id,))
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        # Update last activity
        cursor.execute('''
            UPDATE users SET last_activity = ? WHERE device_id = ?
        ''', (datetime.now().isoformat(), device_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'balance': result['balance']
        })
        
    except Exception as e:
        logger.error(f"Get balance failed: {e}")
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
        
        # Check if device exists
        cursor.execute('SELECT * FROM users WHERE device_id = ?', (device_id,))
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        # Check if already mining
        cursor.execute('''
            SELECT * FROM mining_sessions 
            WHERE device_id = ? AND status = 'active'
        ''', (device_id,))
        
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'error': 'Already mining'}), 400
        
        # Start new mining session
        session_id = str(uuid.uuid4())
        cursor.execute('''
            INSERT INTO mining_sessions 
            (session_id, device_id, start_time, status)
            VALUES (?, ?, ?, 'active')
        ''', (session_id, device_id, datetime.now().isoformat()))
        
        # Update last activity
        cursor.execute('''
            UPDATE users SET last_activity = ? WHERE device_id = ?
        ''', (datetime.now().isoformat(), device_id))
        
        conn.commit()
        conn.close()
        
        # Add mining start transaction
        add_transaction_to_blockchain('mining_start', device_id, 'mining_pool', 0.0,
                                    {'action': 'mining_session_start', 'session_id': session_id})
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'message': 'Mining started successfully'
        })
        
    except Exception as e:
        logger.error(f"Start mining failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/mining/stop', methods=['POST'])
def stop_mining():
    """Stop mining session and calculate rewards"""
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        
        if not device_id:
            return jsonify({'success': False, 'error': 'Device ID required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get active mining session
        cursor.execute('''
            SELECT * FROM mining_sessions 
            WHERE device_id = ? AND status = 'active'
            ORDER BY start_time DESC LIMIT 1
        ''', (device_id,))
        
        session = cursor.fetchone()
        if not session:
            conn.close()
            return jsonify({'success': False, 'error': 'No active mining session'}), 400
        
        # Get user info
        cursor.execute('SELECT * FROM users WHERE device_id = ?', (device_id,))
        user = cursor.fetchone()
        
        # Calculate mining duration and rewards
        start_time = datetime.fromisoformat(session['start_time'])
        end_time = datetime.now()
        duration_seconds = (end_time - start_time).total_seconds()
        duration_minutes = duration_seconds / 60
        
        earned = round(duration_minutes * user['mining_rate'], 4)
        new_balance = round(user['balance'] + earned, 4)
        
        # Update mining session
        cursor.execute('''
            UPDATE mining_sessions 
            SET end_time = ?, duration_seconds = ?, tokens_earned = ?, status = 'completed'
            WHERE session_id = ?
        ''', (end_time.isoformat(), int(duration_seconds), earned, session['session_id']))
        
        # Update user balance and stats
        cursor.execute('''
            UPDATE users 
            SET balance = ?, total_mined = total_mined + ?, last_activity = ?
            WHERE device_id = ?
        ''', (new_balance, earned, datetime.now().isoformat(), device_id))
        
        conn.commit()
        conn.close()
        
        # Add mining reward transaction
        add_transaction_to_blockchain('mining_reward', 'mining_pool', device_id, earned,
                                    {'action': 'mining_reward', 'session_id': session['session_id'],
                                     'duration_minutes': round(duration_minutes, 2)})
        
        return jsonify({
            'success': True,
            'earned': earned,
            'new_balance': new_balance,
            'duration_minutes': round(duration_minutes, 2),
            'message': f'Mining stopped. Earned {earned} SPM'
        })
        
    except Exception as e:
        logger.error(f"Stop mining failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/faucet/claim', methods=['POST'])
def claim_faucet():
    """Claim faucet rewards (100 SPM every 24 hours)"""
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        
        if not device_id:
            return jsonify({'success': False, 'error': 'Device ID required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE device_id = ?', (device_id,))
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        # Check if can claim (24 hours since last claim)
        if user['last_faucet_claim']:
            last_claim = datetime.fromisoformat(user['last_faucet_claim'])
            if datetime.now() - last_claim < timedelta(hours=24):
                remaining = timedelta(hours=24) - (datetime.now() - last_claim)
                hours = int(remaining.total_seconds() // 3600)
                minutes = int((remaining.total_seconds() % 3600) // 60)
                conn.close()
                return jsonify({
                    'success': False, 
                    'error': f'Faucet available in {hours}h {minutes}m'
                }), 400
        
        # Give faucet reward
        faucet_amount = 100.0
        new_balance = round(user['balance'] + faucet_amount, 4)
        
        cursor.execute('''
            UPDATE users 
            SET balance = ?, last_faucet_claim = ?, total_received = total_received + ?, last_activity = ?
            WHERE device_id = ?
        ''', (new_balance, datetime.now().isoformat(), faucet_amount, 
              datetime.now().isoformat(), device_id))
        
        conn.commit()
        conn.close()
        
        # Add faucet transaction
        add_transaction_to_blockchain('faucet', 'faucet_pool', device_id, faucet_amount,
                                    {'action': 'faucet_claim'})
        
        return jsonify({
            'success': True,
            'amount': faucet_amount,
            'new_balance': new_balance,
            'message': f'Claimed {faucet_amount} SPM from faucet'
        })
        
    except Exception as e:
        logger.error(f"Faucet claim failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/transfer', methods=['POST'])
def transfer_spm():
    """Transfer SPM between devices"""
    try:
        data = request.get_json()
        from_device = data.get('from_device')
        to_device = data.get('to_device')
        amount = float(data.get('amount', 0))
        
        if not all([from_device, to_device, amount > 0]):
            return jsonify({'success': False, 'error': 'Invalid transfer data'}), 400
        
        if from_device == to_device:
            return jsonify({'success': False, 'error': 'Cannot transfer to same device'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get sender info
        cursor.execute('SELECT * FROM users WHERE device_id = ?', (from_device,))
        sender = cursor.fetchone()
        
        if not sender:
            conn.close()
            return jsonify({'success': False, 'error': 'Sender device not found'}), 404
        
        if sender['balance'] < amount:
            conn.close()
            return jsonify({'success': False, 'error': 'Insufficient balance'}), 400
        
        # Get or create recipient
        cursor.execute('SELECT * FROM users WHERE device_id = ?', (to_device,))
        recipient = cursor.fetchone()
        
        if not recipient:
            # Create recipient device
            cursor.execute('''
                INSERT INTO users 
                (device_id, balance, mining_rate, registration_time, last_activity)
                VALUES (?, 0.0, 0.1, ?, ?)
            ''', (to_device, datetime.now().isoformat(), datetime.now().isoformat()))
            recipient_balance = 0.0
        else:
            recipient_balance = recipient['balance']
        
        # Perform transfer
        sender_new_balance = round(sender['balance'] - amount, 4)
        recipient_new_balance = round(recipient_balance + amount, 4)
        
        cursor.execute('''
            UPDATE users 
            SET balance = ?, total_sent = total_sent + ?, last_activity = ?
            WHERE device_id = ?
        ''', (sender_new_balance, amount, datetime.now().isoformat(), from_device))
        
        cursor.execute('''
            UPDATE users 
            SET balance = ?, total_received = total_received + ?, last_activity = ?
            WHERE device_id = ?
        ''', (recipient_new_balance, amount, datetime.now().isoformat(), to_device))
        
        conn.commit()
        conn.close()
        
        # Add transfer transaction
        add_transaction_to_blockchain('transfer', from_device, to_device, amount,
                                    {'action': 'peer_transfer'})
        
        return jsonify({
            'success': True,
            'sender_new_balance': sender_new_balance,
            'recipient_new_balance': recipient_new_balance,
            'message': f'Transferred {amount} SPM successfully'
        })
        
    except Exception as e:
        logger.error(f"Transfer failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/blockchain/stats')
def get_blockchain_stats():
    """Get global blockchain statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get stats from system_stats table
        cursor.execute('SELECT stat_name, stat_value FROM system_stats')
        stats_data = {row['stat_name']: row['stat_value'] for row in cursor.fetchall()}
        
        conn.close()
        
        # Update stats before returning
        update_system_stats()
        
        return jsonify({
            'success': True,
            'stats': {
                'total_blocks': int(stats_data.get('total_blocks', 1)),
                'total_users': int(stats_data.get('total_users', 0)),
                'active_users': int(stats_data.get('active_users', 0)),
                'total_transactions': int(stats_data.get('total_transactions', 1)),
                'total_hash_rate': float(stats_data.get('total_hash_rate', 0.0))
            }
        })
        
    except Exception as e:
        logger.error(f"Get blockchain stats failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/blockchain/transactions')
def get_transactions():
    """Get recent blockchain transactions"""
    try:
        limit = min(int(request.args.get('limit', 50)), 100)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM transactions 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (limit,))
        
        transactions = []
        for row in cursor.fetchall():
            transactions.append({
                'id': row['id'],
                'type': row['type'],
                'from': row['from_device'],
                'to': row['to_device'],
                'amount': row['amount'],
                'timestamp': row['timestamp'],
                'block_hash': row['block_hash'],
                'status': row['status']
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'transactions': transactions
        })
        
    except Exception as e:
        logger.error(f"Get transactions failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/blockchain/blocks')
def get_blocks():
    """Get blockchain blocks"""
    try:
        limit = min(int(request.args.get('limit', 20)), 50)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM blockchain_blocks 
            ORDER BY block_number DESC 
            LIMIT ?
        ''', (limit,))
        
        blocks = []
        for row in cursor.fetchall():
            blocks.append({
                'block_number': row['block_number'],
                'block_hash': row['block_hash'],
                'previous_hash': row['previous_hash'],
                'timestamp': row['timestamp'],
                'transactions_count': row['transactions_count'],
                'merkle_root': row['merkle_root']
            })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'blocks': blocks
        })
        
    except Exception as e:
        logger.error(f"Get blocks failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Initialize database on startup
init_database()

# Start background stats updater
def background_stats_updater():
    """Background thread to update stats periodically"""
    while True:
        try:
            time.sleep(60)  # Update every minute
            update_system_stats()
        except Exception as e:
            logger.error(f"Background stats update failed: {e}")

# Start background thread
stats_thread = threading.Thread(target=background_stats_updater, daemon=True)
stats_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)



